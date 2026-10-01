#!/usr/bin/env python3
"""RRM — Infrastructure monitoring and control
Proxmox Auto-Discovery · Prometheus · Loki · Port Scan · RMM
"""
from flask import Flask, render_template, jsonify, request, redirect, url_for, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.parse
import ssl
import subprocess
import threading
import socket
import sqlite3
import json
import time
import os
import re
import paramiko as _paramiko
import datetime as _dt
import secrets as _sec

# In der Oberflaeche gesetzte Einstellungen (Datei im Datenverzeichnis) haben Vorrang vor der Umgebung.
CONFIG_FILE = os.path.join(os.path.dirname(os.environ.get('AUDIT_DB', '/data/audit.db')) or '.', 'config.env')
def _read_config_file():
    vals = {}
    try:
        for line in open(CONFIG_FILE, encoding='utf-8'):
            line = line.rstrip('\n')
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                vals[k.strip()] = v
    except FileNotFoundError:
        pass
    return vals
os.environ.update(_read_config_file())

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

APP_VERSION = '41'

app = Flask(__name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)

def _load_secret_key():
    """SECRET_KEY env > persisted random key in /data > legacy fallback.
    A guessable secret key lets anyone forge admin session cookies."""
    k = os.environ.get('SECRET_KEY')
    if k:
        return k
    try:
        data_dir = os.path.dirname(os.environ.get('AUDIT_DB', '/data/audit.db')) or '.'
        p = os.path.join(data_dir, 'secret_key')
        if os.path.exists(p):
            k = open(p).read().strip()
            if k:
                return k
        k = _sec.token_hex(32)
        with open(p, 'w') as f:
            f.write(k)
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
        return k
    except Exception as e:
        print(f'[secret] persist failed ({e}) — using legacy key')
        return _sec.token_hex(32)

app.secret_key = _load_secret_key()
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'

# Websocket CORS: same-origin by default; extra origins via CORS_ORIGINS=a,b
_cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
socketio = SocketIO(app, cors_allowed_origins=_cors_origins or None, async_mode='threading')

@app.after_request
def _security_headers(resp):
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('Referrer-Policy', 'same-origin')
    return resp

PROXMOX_HOST = os.environ.get('PROXMOX_HOST', '')
PROXMOX_API  = f"https://{PROXMOX_HOST}:8006/api2/json"
PROXMOX_NODE = os.environ.get('PROXMOX_NODE', '')   # leer = Node des konfigurierten Hosts
PROXMOX_USER = os.environ.get('PROXMOX_USER', 'root@pam')
PROXMOX_PASS = os.environ.get('PROXMOX_PASS', '')
# Alternative zum Root-Passwort: API-Token (user@realm!tokenid=secret), z.B. mit PVEAuditor-Rolle
PROXMOX_TOKEN = os.environ.get('PROXMOX_TOKEN', '')
MCP_TOKEN    = os.environ.get('MCP_TOKEN', '')
PROMETHEUS   = os.environ.get('PROMETHEUS_URL', '')
LOKI_URL     = os.environ.get('LOKI_URL', '')
GRAFANA_URL  = os.environ.get('GRAFANA_URL', '')
DOKPLOY_URL  = os.environ.get('DOKPLOY_URL', '')
DOKPLOY_KEY  = os.environ.get('DOKPLOY_API_KEY', '')
LITELLM_URL  = os.environ.get('LITELLM_URL', '')
LITELLM_KEY  = os.environ.get('LITELLM_KEY', '')
COOLIFY_URL    = os.environ.get('COOLIFY_URL', '')
COOLIFY_KEY    = os.environ.get('COOLIFY_API_KEY', '')
UNIFI_URL      = (os.environ.get('UNIFI_URL') or os.environ.get('UNIFI_HOST', '')).rstrip('/')
if UNIFI_URL and '://' not in UNIFI_URL:
    UNIFI_URL = 'https://' + UNIFI_URL
UNIFI_USER     = os.environ.get('UNIFI_USER', '')
UNIFI_PASS     = os.environ.get('UNIFI_PASS', '')
UNIFI_SITE     = os.environ.get('UNIFI_SITE', 'default')
GL_AGENT_TOKEN = os.environ.get('GL_AGENT_TOKEN', '')
AGENT_PORT     = int(os.environ.get('AGENT_PORT', 9998))

# Per-host agent tokens — env vars: GL_TOKEN_<HOST_KEY_UPPER> (e.g. GL_TOKEN_NOVA)
# Falls back to GL_AGENT_TOKEN if not set (backward-compatible)
def _agent_token(ip_or_key: str) -> str:
    # Lazy reverse-map so STATIC_HOSTS is already defined when called
    key = ip_or_key
    for k, v in STATIC_HOSTS.items():
        if v[1] == ip_or_key:
            key = k
            break
    env_name = f'GL_TOKEN_{key.upper().replace("-", "_")}'
    return os.environ.get(env_name, GL_AGENT_TOKEN)
LXC_SSH_USER   = os.environ.get('LXC_SSH_USER', 'root')
LXC_SSH_PASS   = os.environ.get('LXC_SSH_PASS', '')
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
# Öffentliche Status-Seite (/status, ohne Login; zeigt nur Namen + up/down, keine IPs).
# Deaktivieren mit PUBLIC_STATUS=0
PUBLIC_STATUS    = os.environ.get('PUBLIC_STATUS', '1') == '1'

# Per-host SSH overrides: key → (user, pass)
SSH_OVERRIDES = {}   # optional: host-key -> (user, pass)
AUDIT_DB       = os.environ.get('AUDIT_DB', '/data/audit.db')
os.makedirs(os.path.dirname(AUDIT_DB) or '.', exist_ok=True)

# Hermes agent API keys: env GL_HERMES_KEY_<NAME>=<token>
HERMES_AGENTS  = {v: k.replace('GL_HERMES_KEY_', '').lower()
                  for k, v in os.environ.items() if k.startswith('GL_HERMES_KEY_')}
# Entwicklungs-Schluessel nur auf ausdrueckliche Anforderung (GL_HERMES_DEV_KEY setzen).
# Frueher stand hier ein fester Schluessel im Code — der galt damit auf jeder Instanz.
_dev_key = os.environ.get('GL_HERMES_DEV_KEY', '')
if not HERMES_AGENTS and _dev_key:
    HERMES_AGENTS[_dev_key] = 'hermes-dev'
def _persisted_secret(name):
    """Zufaelliges Secret einmalig erzeugen und in /data ablegen (Zero-Config-Start)."""
    p = os.path.join(os.path.dirname(AUDIT_DB) or '.', name)
    try:
        if os.path.exists(p):
            v = open(p).read().strip()
            if v:
                return v
        v = _sec.token_hex(24)
        with open(p, 'w') as f:
            f.write(v)
        os.chmod(p, 0o600)
        return v
    except Exception:
        return _sec.token_hex(24)

GL_AGENT_TOKEN = GL_AGENT_TOKEN or _persisted_secret('agent_token')
MCP_TOKEN      = MCP_TOKEN or _persisted_secret('mcp_token')
CACHE_TTL     = 5
DISCOVERY_TTL = 90

# Optionaler Administrator aus der Umgebung (ADMIN_USER / ADMIN_PASSWORD).
# Ohne gesetztes Passwort gibt es keinen Code-Fallback mehr — die Benutzer aus der
# users-Tabelle funktionieren davon unabhaengig weiter.
USERS = {name: generate_password_hash(pw) for name, pw in (
    (os.environ.get('ADMIN_USER', 'admin').strip().lower(), os.environ.get('ADMIN_PASSWORD', '')),
) if pw}

SCAN_PORTS = [
    80, 81, 443, 1713, 2000, 3000, 3001, 3007, 3010, 3023, 3033, 3034,
    3100, 3389, 4000, 4001, 4010, 5000, 5001, 5002, 5003, 5004,
    5006, 5038, 5060, 5432, 5678, 5984, 6080, 6333, 6334, 6379,
    7878, 8000, 8001, 8002, 8006, 8065, 8080, 8086, 8088, 8096, 8123,
    8181, 8443, 8880, 8888, 8989, 9000, 9001, 9090, 9100, 9117,
    9443, 9696, 9998, 11434,
]

PORT_NAMES = {
    80:    ('HTTP',           True),
    443:   ('HTTPS',          True),
    1713:  ('Web App',         True),
    3000:  ('Web UI',         True),
    3010:  ('Dograh UI',      True),
    3023:  ('MCP Server',     True),
    3033:  ('Moto Poschung',  True),
    3034:  ('BesorgsDir',     True),
    3100:  ('Loki',           True),
    4000:  ('LiteLLM',        True),
    4001:  ('LiteLLM Premium',True),
    4010:  ('AI Router',      True),
    5006:  ('Actual Budget',  True),
    5060:  ('SIP/VoIP',       False),
    5432:  ('PostgreSQL',     False),
    5678:  ('n8n',            True),
    5984:  ('CouchDB',        True),
    6333:  ('Qdrant API',     True),
    6334:  ('Qdrant gRPC',    False),
    7878:  ('Radarr',         True),
    8000:  ('Web API',        True),
    8001:  ('Nova Call API',  True),
    8002:  ('Google MCP',     True),
    8006:  ('Proxmox',        True),
    8080:  ('HTTP Alt',       True),
    8086:  ('InfluxDB',       True),
    8088:  ('Chronograf',     True),
    8096:  ('Jellyfin',       True),
    8065:  ('Mattermost',     True),
    8123:  ('Home Assistant', True),
    8181:  ('Dashboard',      True),
    3007:  ('MT5 Trading',    True),
    8443:  ('HTTPS Alt',      True),
    8888:  ('Web UI',         True),
    8989:  ('Sonarr',         True),
    2000:  ('SCCP/VoIP',      False),
    3389:  ('xRDP',           False),
    5001:  ('Python API',     True),
    5002:  ('Python API',     True),
    5003:  ('Python API',     True),
    5004:  ('Python API',     True),
    5038:  ('Asterisk AMI',   False),
    6080:  ('noVNC',          True),
    6379:  ('Redis',          False),
    8082:  ('qBittorrent',    True),
    8880:  ('Uvicorn API',    True),
    10081: ('Nextcloud',      True),
    32400: ('Plex',           True),
    9000:  ('MinIO API',      True),
    9001:  ('MinIO Web',      True),
    9090:  ('Prometheus',     True),
    9100:  ('Node Exporter',  False),
    9117:  ('Jackett',        True),
    9443:  ('Portainer',      True),
    9696:  ('Prowlarr',       True),
    9998:  ('GL Agent',       False),
    11434: ('Ollama',         True),
}

# Host-Register: key -> (name, ip, icon, category, ct_id, services[(port, svc_name, has_http, desc)])
# Startet leer und wird zur Laufzeit gefuellt: Proxmox-Erkennung, registrierte Agenten,
# manuell hinzugefuegte Hosts (Tabelle manual_hosts) und konfigurierte Infrastruktur.
STATIC_HOSTS = {}
DEPENDENCIES = {}
SERVICE_URLS = {}

def _load_external_links():
    try:
        v = json.loads(os.environ.get('EXTERNAL_LINKS', '') or '[]')
        return [l for l in v if isinstance(l, dict) and l.get('url')]
    except Exception:
        return []
EXTERNAL_LINKS = _load_external_links()

# ─── LOGIN BRUTE-FORCE SCHUTZ ─────────────────
LOGIN_MAX_FAILS = int(os.environ.get('LOGIN_MAX_FAILS', '5'))
LOGIN_BLOCK_S   = int(os.environ.get('LOGIN_BLOCK_S', '300'))
_login_fails = {}   # ip → [fail-timestamps innerhalb des Fensters]
_login_fails_lk = threading.Lock()

def _login_blocked(ip):
    now = time.time()
    with _login_fails_lk:
        fails = [t for t in _login_fails.get(ip, []) if now - t < LOGIN_BLOCK_S]
        if fails:
            _login_fails[ip] = fails
        else:
            _login_fails.pop(ip, None)
        return len(fails) >= LOGIN_MAX_FAILS

def _login_fail_register(ip):
    with _login_fails_lk:
        _login_fails.setdefault(ip, []).append(time.time())

def _login_fail_clear(ip):
    with _login_fails_lk:
        _login_fails.pop(ip, None)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login_page'))
        # legacy sessions without a role are treated as admin (owner) for safety
        if session.get('role', 'admin') != 'admin':
            return jsonify({'ok': False, 'error': 'Nur Admins dürfen das'}), 403
        return f(*args, **kwargs)
    return decorated

def _users_ensure():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, pw_hash TEXT, role TEXT DEFAULT 'viewer',
        created_at TEXT, last_login TEXT)''')
    for col, ddl in [('mfa_secret', 'TEXT'), ('mfa_enabled', 'INTEGER DEFAULT 0')]:
        try:
            conn.execute(f'ALTER TABLE users ADD COLUMN {col} {ddl}')
        except Exception:
            pass
    if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        now = time.strftime('%Y-%m-%dT%H:%M:%S')
        for u, h in USERS.items():   # seed existing accounts as admins
            conn.execute('INSERT OR IGNORE INTO users (username,pw_hash,role,created_at) VALUES (?,?,?,?)', (u, h, 'admin', now))
    conn.commit(); conn.close()

def _user_get(username):
    _users_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute('SELECT username,pw_hash,role FROM users WHERE username=?', (username,)).fetchone()
    conn.close()
    return {'username': row[0], 'pw_hash': row[1], 'role': row[2]} if row else None

def _user_mfa(username):
    _users_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute('SELECT mfa_secret, mfa_enabled FROM users WHERE username=?', (username,)).fetchone()
    conn.close()
    return {'secret': row[0], 'enabled': bool(row[1])} if row else None

def _login_finalize(u, role):
    session.clear()
    session['authenticated'] = True
    session['username'] = u
    session['role'] = role
    session.permanent = True
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('UPDATE users SET last_login=? WHERE username=?', (time.strftime('%Y-%m-%dT%H:%M:%S'), u))
        conn.commit(); conn.close()
    except Exception:
        pass
    try:
        _audit(u, 'login', '', f'erfolgreich · {request.remote_addr or ""}')
    except Exception:
        pass

class Cache:
    def __init__(self):
        self._d = {}; self._ts = {}; self._lk = threading.Lock()
    def get(self, k, ttl=CACHE_TTL):
        with self._lk:
            if k in self._d and time.time() - self._ts.get(k, 0) < ttl:
                return self._d[k]
        return None
    def set(self, k, v):
        with self._lk:
            self._d[k] = v; self._ts[k] = time.time()
    def bust(self, k=None):
        with self._lk:
            if k: self._d.pop(k, None); self._ts.pop(k, None)
            else: self._d.clear(); self._ts.clear()

cache        = Cache()
ping_history = {}
ph_lock      = threading.Lock()
_px_ticket   = None
_px_expiry   = 0
_px_lock     = threading.Lock()

# SSH terminal sessions: socket-id → (paramiko_client, channel)
_ssh_sessions     = {}
_ssh_sessions_lk  = threading.Lock()

def _init_audit():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('''CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, user TEXT, action TEXT, host_key TEXT, detail TEXT
        )''')
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[audit] init failed: {e}')

def _audit(user, action, host_key='', detail=''):
    try:
        ts = time.strftime('%Y-%m-%dT%H:%M:%S')
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('INSERT INTO audit (ts,user,action,host_key,detail) VALUES (?,?,?,?,?)',
                     (ts, str(user)[:40], action[:40], host_key[:40], str(detail)[:500]))
        conn.commit(); conn.close()
    except Exception:
        pass

def _who():
    """The acting user for audit: logged-in username, falling back to client IP."""
    try:
        return session.get('username') or (request.remote_addr or '?')
    except Exception:
        return '?'

def _audit_user(action, host_key='', detail=''):
    """Audit an action attributed to the current user, with client IP appended."""
    try:
        ip = request.remote_addr or ''
    except Exception:
        ip = ''
    d = f'{detail} · {ip}' if ip else detail
    _audit(_who(), action, host_key, d)

# ─── CRON SCHEDULER ───────────────────────────
import uuid as _uuid

def _init_host_meta():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('''CREATE TABLE IF NOT EXISTS host_meta (
            host_key TEXT PRIMARY KEY,
            category TEXT,
            display_name TEXT,
            notes TEXT,
            updated_at TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS agent_tokens (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE,
            token TEXT UNIQUE,
            created_at TEXT,
            last_seen TEXT
        )''')
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[host_meta] init failed: {e}')

def _get_host_meta():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute('SELECT host_key,category,display_name,notes FROM host_meta').fetchall()
        conn.close()
        return {r[0]: {'category': r[1], 'display_name': r[2], 'notes': r[3]} for r in rows}
    except Exception:
        return {}

# ─── APP-SETTINGS (key/value, u.a. Alert-Schwellwerte) ─────────────────────
DEFAULT_THRESHOLDS = {'cpu_warn': 90, 'ram_warn': 90, 'disk_crit': 85, 'ssl_warn_days': 30}

def _init_settings():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)')
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[settings] init failed: {e}')

def _setting_get(key, default=None):
    try:
        conn = sqlite3.connect(AUDIT_DB)
        row = conn.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default

def _setting_set(key, value):
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('INSERT INTO app_settings (key,value) VALUES (?,?) '
                 'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
    conn.commit(); conn.close()

def _get_thresholds():
    cached = cache.get('thresholds', ttl=30)
    if cached is not None:
        return cached
    thr = dict(DEFAULT_THRESHOLDS)
    try:
        saved = json.loads(_setting_get('alert_thresholds') or '{}')
        for k in thr:
            if k in saved:
                thr[k] = float(saved[k])
    except Exception:
        pass
    cache.set('thresholds', thr)
    return thr

# ─── AGENT-REGISTRY (Self-Registration / Heartbeat / Stale-Erkennung) ──────
AGENT_STALE_S = int(os.environ.get('AGENT_STALE_S', '150'))

def _init_agents():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('''CREATE TABLE IF NOT EXISTS agents (
            ip TEXT PRIMARY KEY,
            hostname TEXT,
            version TEXT,
            cpu_pct REAL,
            mem_pct REAL,
            disk_pct REAL,
            ports_json TEXT,
            nanoclaw INTEGER,
            first_seen INTEGER,
            last_seen INTEGER
        )''')
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[agents] init failed: {e}')

def _agent_register(ip, payload):
    now = int(time.time())
    disk = (payload.get('disk') or {})
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''INSERT INTO agents
        (ip,hostname,version,cpu_pct,mem_pct,disk_pct,ports_json,nanoclaw,first_seen,last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ip) DO UPDATE SET
          hostname=excluded.hostname, version=excluded.version,
          cpu_pct=excluded.cpu_pct, mem_pct=excluded.mem_pct, disk_pct=excluded.disk_pct,
          ports_json=excluded.ports_json, nanoclaw=excluded.nanoclaw,
          last_seen=excluded.last_seen''',
        (ip, payload.get('hostname'), payload.get('agent_version'),
         payload.get('cpu_pct'), payload.get('mem_pct'), disk.get('pct'),
         json.dumps(payload.get('listening_ports') or []),
         1 if payload.get('nanoclaw') else 0, now, now))
    conn.commit(); conn.close()

def _agents_list():
    now = int(time.time())
    try:
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute('SELECT ip,hostname,version,cpu_pct,mem_pct,disk_pct,ports_json,nanoclaw,first_seen,last_seen FROM agents').fetchall()
        conn.close()
    except Exception:
        return []
    out = []
    for r in rows:
        out.append({'ip': r[0], 'hostname': r[1], 'version': r[2],
                    'cpu_pct': r[3], 'mem_pct': r[4], 'disk_pct': r[5],
                    'ports': json.loads(r[6] or '[]'), 'nanoclaw': bool(r[7]),
                    'first_seen': r[8], 'last_seen': r[9],
                    'age_s': now - (r[9] or 0),
                    'stale': (now - (r[9] or 0)) > AGENT_STALE_S})
    return out

@app.route('/api/agent/register', methods=['POST'])
def api_agent_register():
    # Agenten authentifizieren per Bearer-Token (keine Session).
    auth = request.headers.get('Authorization', '')
    if auth != f'Bearer {GL_AGENT_TOKEN}':
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    payload = request.get_json(silent=True) or {}
    ip = payload.get('ip') or request.remote_addr
    try:
        _agent_register(ip, payload)
        return jsonify({'ok': True, 'ip': ip, 'stale_after_s': AGENT_STALE_S})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/agents')
@login_required
def api_agents():
    agents = _agents_list()
    return jsonify({'agents': agents, 'count': len(agents),
                    'online': sum(1 for a in agents if not a['stale']),
                    'stale': sum(1 for a in agents if a['stale'])})

# ─── METRICS HISTORY / SLA / PREDICTIVE ──────────────────────────────────

def _init_metrics_tables():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('''CREATE TABLE IF NOT EXISTS metrics_history (
            ts INTEGER NOT NULL, host_key TEXT NOT NULL,
            cpu REAL, ram REAL, disk REAL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_mh ON metrics_history(host_key, ts)')
        conn.execute('''CREATE TABLE IF NOT EXISTS uptime_log (
            ts INTEGER NOT NULL, host_key TEXT NOT NULL, ok INTEGER NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ul ON uptime_log(host_key, ts)')
        conn.execute('''CREATE TABLE IF NOT EXISTS ssl_status (
            host TEXT PRIMARY KEY, days_left INTEGER,
            expiry TEXT, checked_at INTEGER, error TEXT
        )''')
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[metrics] init: {e}')

def _store_metrics():
    live = cache.get('live')
    if not live: return
    ts = int(time.time())
    try:
        conn = sqlite3.connect(AUDIT_DB)
        for h in live.get('hosts', []):
            ag = h.get('agent') or {}
            m  = h.get('metrics') or {}
            # Store the resolved metrics (Proxmox per-VMID for LXCs); fall back to the
            # agent only when missing. The agent reads host-wide /proc inside an LXC,
            # so storing it first poisoned the CPU history with ~100% for every container.
            cpu = m.get('cpu') if m.get('cpu') is not None else ag.get('cpu_pct')
            ram = m.get('ram') if m.get('ram') is not None else ag.get('mem_pct')
            dsk = m.get('disk_pct') if m.get('disk_pct') is not None else (ag.get('disk') or {}).get('pct')
            ok  = 1 if h['status'] == 'online' else 0
            conn.execute('INSERT INTO metrics_history (ts,host_key,cpu,ram,disk) VALUES (?,?,?,?,?)',
                        (ts, h['key'], cpu, ram, dsk))
            conn.execute('INSERT INTO uptime_log (ts,host_key,ok) VALUES (?,?,?)',
                        (ts, h['key'], ok))
        cutoff = ts - 46 * 86400
        conn.execute('DELETE FROM metrics_history WHERE ts < ?', (cutoff,))
        conn.execute('DELETE FROM uptime_log WHERE ts < ?', (cutoff,))
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[metrics] store: {e}')

def _metrics_bg():
    time.sleep(65)
    while True:
        try: _store_metrics()
        except Exception as e: print(f'[metrics_bg] {e}')
        time.sleep(60)

def get_sla_pct(host_key, days=30):
    try:
        cutoff = int(time.time()) - days * 86400
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute('SELECT ok FROM uptime_log WHERE host_key=? AND ts>?',
                           (host_key, cutoff)).fetchall()
        conn.close()
        if len(rows) < 30: return None
        return round(sum(r[0] for r in rows) / len(rows) * 100, 2)
    except Exception:
        return None

def predict_days_until(host_key, metric='disk', threshold=90.0, hours_back=168):
    try:
        cutoff = int(time.time()) - hours_back * 3600
        col = metric if metric in ('cpu', 'ram', 'disk') else 'disk'
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute(f'SELECT ts,{col} FROM metrics_history WHERE host_key=? AND ts>? AND {col} IS NOT NULL ORDER BY ts',
                           (host_key, cutoff)).fetchall()
        conn.close()
        if len(rows) < 12: return None
        xs = [r[0] for r in rows]; ys = [r[1] for r in rows]
        n = len(xs)
        xm = sum(xs)/n; ym = sum(ys)/n
        num = sum((xs[i]-xm)*(ys[i]-ym) for i in range(n))
        den = sum((xi-xm)**2 for xi in xs)
        if den == 0 or num <= 0: return None
        slope = num/den
        curr  = ys[-1]
        if curr >= threshold: return 0
        return round((threshold - curr) / slope / 86400, 1)
    except Exception:
        return None

# ─── SSL CERT MONITOR ─────────────────────────────────────────────────────

def check_ssl_expiry(host, port=443):
    import ssl, socket
    ctx_verify = ssl.create_default_context()
    ctx_noverify = ssl.create_default_context()
    ctx_noverify.check_hostname = False
    ctx_noverify.verify_mode = ssl.CERT_NONE
    def _parse_cert(ctx, host, port):
        with ctx.wrap_socket(socket.create_connection((host, port), timeout=8),
                             server_hostname=host) as s:
            cert = s.getpeercert()
        if not cert:
            return None
        not_after = cert.get('notAfter', '')
        exp = _dt.datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
        days = (exp - _dt.datetime.utcnow()).days
        return {'days_left': days, 'expiry': not_after, 'valid': True}
    try:
        return _parse_cert(ctx_verify, host, port)
    except ssl.SSLCertVerificationError:
        try:
            _parse_cert(ctx_noverify, host, port)
            return {'days_left': None, 'expiry': None, 'valid': False, 'error': 'self-signed'}
        except Exception as e2:
            return {'days_left': None, 'error': str(e2)[:60], 'valid': False}
    except Exception as e:
        return {'days_left': None, 'error': str(e)[:60], 'valid': False}

_ssl_cache    = {}
_ssl_cache_ts = 0

def get_ssl_all():
    global _ssl_cache_ts
    now = int(time.time())
    if now - _ssl_cache_ts < 21600 and _ssl_cache:
        return _ssl_cache
    https_services = []
    for key, (name, ip, icon, cat, ct_id, svcs) in STATIC_HOSTS.items():
        for port, svc_name, has_http, desc in svcs:
            if port in (443, 8443, 9443):
                https_services.append((key, ip, port, svc_name))
    results = {}
    def _chk(item):
        key, ip, port, svc = item
        return key, svc, check_ssl_expiry(ip, port)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for key, svc, r in pool.map(_chk, https_services):
            results.setdefault(key, {})[svc] = r
    try:
        conn = sqlite3.connect(AUDIT_DB)
        for key, smap in results.items():
            for svc, r in smap.items():
                conn.execute('INSERT OR REPLACE INTO ssl_status (host,days_left,expiry,checked_at,error) VALUES (?,?,?,?,?)',
                            (f'{key}/{svc}', r.get('days_left'), r.get('expiry'), now, r.get('error')))
        conn.commit(); conn.close()
    except Exception: pass
    _ssl_cache.update(results)
    _ssl_cache_ts = now
    return _ssl_cache

# ─── TELEGRAM ─────────────────────────────────────────────────────────────

_tg_sent = {}

def _tg_send(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        data = json.dumps({'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}).encode()
        req  = urllib.request.Request(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage', data=data)
        req.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f'[Telegram] {e}')
        return False

def _tg_alert(key, msg, cooldown_s=3600):
    now  = time.time()
    last = _tg_sent.get(key, 0)
    if now - last < cooldown_s: return
    _tg_sent[key] = now
    host_name = STATIC_HOSTS.get(key.split(':')[0], (key,))[0]
    _tg_send(f'🚨 *{BRAND}*\n*Host:* {host_name}\n*Problem:* {msg}\n_{time.strftime("%H:%M:%S")}_')

def _tg_check_alerts(hosts_data):
    thr = _get_thresholds()
    for h in hosts_data:
        key  = h['key']
        name = h['name']
        ag   = h.get('agent') or {}
        m    = h.get('metrics') or {}
        if h['status'] == 'offline':
            _tg_alert(f'{key}:offline', f'{name} ({h["ip"]}) ist offline 🔴')
        cpu = (m.get('cpu') if m.get('cpu') is not None else ag.get('cpu_pct', 0)) or 0
        dsk = (m.get('disk_pct') if m.get('disk_pct') is not None else (ag.get('disk') or {}).get('pct', 0)) or 0
        if cpu > thr['cpu_warn']: _tg_alert(f'{key}:cpu', f'{name}: CPU {cpu:.0f}% ⚡')
        if dsk > thr['disk_crit']: _tg_alert(f'{key}:disk', f'{name}: Disk {dsk}% 💾')
        pred = h.get('disk_pred_days')
        if pred is not None and pred < 5:
            _tg_alert(f'{key}:disk_pred', f'{name}: Disk voll in ~{pred} Tagen ⚠️', cooldown_s=86400)
        ssl_d = h.get('ssl_min_days')
        if ssl_d is not None and ssl_d < 15:
            _tg_alert(f'{key}:ssl', f'{name}: SSL Cert läuft in {ssl_d} Tagen ab 🔒', cooldown_s=86400)

# ─── BACKUP MONITOR ───────────────────────────────────────────────────────

def get_backup_jobs():
    cached = cache.get('backup_jobs', ttl=300)
    if cached is not None: return cached
    try:
        resp = _px(f'/nodes/{PROXMOX_NODE}/tasks?typefilter=vzdump&limit=30')
        if not resp: return None
        jobs = []
        for t in resp.get('data', []):
            st = t.get('status', '')
            ok = (st == 'OK')
            dur = ''
            if t.get('endtime') and t.get('starttime'):
                secs = t['endtime'] - t['starttime']
                dur  = f'{secs//60}m {secs%60}s'
            jobs.append({
                'id':        t.get('id', '?'),
                'status':    st or 'running',
                'ok':        ok,
                'starttime': t.get('starttime'),
                'duration':  dur,
            })
        result = {'jobs': jobs, 'ts': int(time.time()),
                  'last_ok': max((j['starttime'] for j in jobs if j['ok']), default=None)}
        cache.set('backup_jobs', result)
        return result
    except Exception as e:
        print(f'[Backup] {e}')
        return None

def _init_crons():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('''CREATE TABLE IF NOT EXISTS crons (
            id TEXT PRIMARY KEY,
            name TEXT,
            host_key TEXT,
            command TEXT,
            interval_min INTEGER DEFAULT 60,
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            last_run TEXT,
            last_ok INTEGER,
            last_result TEXT,
            next_run TEXT
        )''')
        # multi-host targets + named schedule + per-host results (added later)
        for col, ddl in [('targets_json', 'TEXT'), ('schedule', "TEXT DEFAULT 'manual'"),
                         ('last_results', 'TEXT'), ('created_by', 'TEXT')]:
            try:
                conn.execute(f'ALTER TABLE crons ADD COLUMN {col} {ddl}')
            except Exception:
                pass
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[cron] init failed: {e}')

# Named schedules → minutes until next run (None = manual / never auto)
_SCHEDULE_MIN = {'hourly': 60, 'daily': 1440, 'weekly': 10080, 'monthly': 43200}

def _schedule_next(schedule):
    """Return ISO timestamp for the next run, or None for manual schedules."""
    s = (schedule or 'manual').strip()
    mins = None
    if s in _SCHEDULE_MIN:
        mins = _SCHEDULE_MIN[s]
    elif s.startswith('every:'):
        try:
            mins = max(1, int(s.split(':', 1)[1]))
        except Exception:
            mins = None
    if mins is None:
        return None
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() + mins * 60))

def _all_lxc_targets():
    """All host_keys that are LXCs (have a VMID) → runnable via pct exec."""
    keys = [k for k, v in STATIC_HOSTS.items() if v[4]]
    try:
        live = cache.get('live')
        for h in (live or {}).get('hosts', []):
            if h.get('ct_id') and h['key'] not in keys:
                keys.append(h['key'])
    except Exception:
        pass
    return keys

def _resolve_cron_targets(targets_json, host_key):
    """Parse a task's target spec into a concrete list of host_keys."""
    tgts = []
    try:
        tgts = json.loads(targets_json) if targets_json else []
    except Exception:
        tgts = []
    if not tgts and host_key:
        tgts = [host_key]              # legacy single-host crons
    if 'all' in tgts:
        return _all_lxc_targets()
    return [t for t in tgts if t]

def _run_cron_job(cron_id, by='scheduler'):
    """Run a scheduled task across all its target LXCs via Proxmox pct exec."""
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute('SELECT id,name,host_key,command,targets_json,schedule FROM crons WHERE id=?',
                       (cron_id,)).fetchone()
    conn.close()
    if not row:
        return
    cid, name, host_key, command, targets_json, schedule = row
    targets = _resolve_cron_targets(targets_json, host_key)
    results, all_ok = {}, True
    if not targets:
        results['_'] = {'ok': False, 'out': 'Keine Ziel-Hosts'}; all_ok = False
    for hk in targets:
        vmid = _host_vmid(hk)
        if not vmid:
            results[hk] = {'ok': False, 'out': 'keine VMID (kein LXC erreichbar)'}; all_ok = False
            continue
        try:
            out = _prox_exec(vmid, command, timeout=600)
            ok = 'command not found' not in out.lower()
            results[hk] = {'ok': ok, 'out': out.strip()[-4000:]}
            all_ok = all_ok and ok
        except Exception as ex:
            results[hk] = {'ok': False, 'out': str(ex)[:500]}; all_ok = False

    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    nxt = _schedule_next(schedule)        # None for manual → won't auto-recur
    ok_n = sum(1 for r in results.values() if r['ok'])
    summary = f'{ok_n}/{len(results)} OK'
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('UPDATE crons SET last_run=?,last_ok=?,last_result=?,last_results=?,next_run=? WHERE id=?',
                 (now, int(all_ok), summary, json.dumps(results), nxt, cron_id))
    conn.commit(); conn.close()
    _audit(by, 'task_run', '', f'{name}: {summary}')
    try:
        _nc_log('', 'task_run', f'{name} ({len(targets)} Hosts)', summary, 'info' if all_ok else 'warn')
    except Exception:
        pass

def _cron_bg():
    while True:
        try:
            now_str = time.strftime('%Y-%m-%dT%H:%M:%S')
            conn = sqlite3.connect(AUDIT_DB)
            due = conn.execute(
                "SELECT id FROM crons WHERE enabled=1 AND next_run IS NOT NULL AND next_run <= ?",
                (now_str,)
            ).fetchall()
            conn.close()
            for (cron_id,) in due:
                threading.Thread(target=_run_cron_job, args=(cron_id,), daemon=True).start()
        except Exception:
            pass
        time.sleep(30)

# ══════════════════════════════════════════════════════
# NANOCLAW — Autonomous Self-Healing Engine
# ══════════════════════════════════════════════════════

_nc_state     = {}      # { host_key: { containers: {name: was_up}, ... } }
_nc_cooldowns = {}      # { 'host_key:action': last_ts }
_nc_events    = []      # ring buffer, max 300 entries

# Containers to never auto-restart (infrastructure, their restart policy handles them)
_NC_NO_RESTART = {'promtail', 'node-exporter', 'dokploy-postgres', 'dokploy-redis',
                  'dokploy-traefik', 'dokploy', 'portainer'}

# Log patterns for container diagnostics
_NC_DIAG_PATTERNS = [
    (r'out of memory|oom.kill|killed process',
     'OOM Kill',
     'Container wegen Speichermangel beendet. RAM-Limit erhöhen oder Memory-Leak im App prüfen.'),
    (r'permission denied',
     'Permission Denied',
     'Berechtigungsproblem. Volume-Mounts, User-ID oder Datei-ACLs prüfen.'),
    (r'address already in use|bind.*failed|port.*in use',
     'Port belegt',
     'Ein anderer Prozess nutzt den Port. `ss -tlnp` auf dem Host ausführen.'),
    (r'no space left on device',
     'Disk voll',
     'Kein Speicherplatz. Nanoclaw Disk-Cleanup wird automatisch ausgelöst.'),
    (r'cannot connect|connection refused|dial.*refused',
     'Verbindungsfehler',
     'Abhängiger Service nicht erreichbar. Startrekhenfolge oder Netzwerk prüfen.'),
    (r'error response from daemon|docker.*error',
     'Docker-Fehler',
     'Docker-Daemon-Problem. `systemctl status docker` auf dem Host prüfen.'),
    (r'exec format error',
     'Architektur-Mismatch',
     'Image für falsche CPU-Architektur gebaut (arm64 vs amd64).'),
    (r'exit code[: ]+[1-9]|exited with code [1-9]',
     'Non-Zero Exit',
     'Prozess mit Fehler beendet. Umgebungsvariablen oder Konfiguration prüfen.'),
    (r'certificate.*expired|ssl.*error|tls.*error',
     'TLS/SSL-Fehler',
     'Zertifikat abgelaufen oder ungültig. Cert-Manager oder manuelle Erneuerung nötig.'),
]

def _nc_cooldown_ok(key, action, seconds):
    ck = f'{key}:{action}'
    if time.time() - _nc_cooldowns.get(ck, 0) < seconds:
        return False
    _nc_cooldowns[ck] = time.time()
    return True

def _nc_log(host_key, action, detail, result, severity='info'):
    ev = {
        'ts':       int(time.time()),
        'ts_str':   time.strftime('%Y-%m-%dT%H:%M:%S'),
        'host':     host_key,
        'action':   action,
        'detail':   detail,
        'result':   result,
        'severity': severity,
    }
    _nc_events.append(ev)
    if len(_nc_events) > 300:
        _nc_events.pop(0)
    _audit('nanoclaw', action, host_key, f'{detail[:120]} → {result[:120]}')
    print(f'[Nanoclaw] [{severity.upper()}] {host_key} | {action} | {detail} → {result}')

def _nc_ssh(ip, cmd, timeout=20):
    override = SSH_OVERRIDES.get(ip, {})
    user = override[0] if isinstance(override, tuple) else LXC_SSH_USER
    pwd  = override[1] if isinstance(override, tuple) else LXC_SSH_PASS
    ssh  = _paramiko.SSHClient()
    ssh.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
    ssh.connect(ip, port=22, username=user, password=pwd,
                timeout=10, look_for_keys=False, allow_agent=False)
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', 'replace').strip()
    err = e.read().decode('utf-8', 'replace').strip()
    ssh.close()
    return out, err

def _nc_agent_restart(host_key, ip, container_name):
    try:
        data = json.dumps({'name': container_name}).encode()
        req  = urllib.request.Request(
            f'http://{ip}:{AGENT_PORT}/restart', data=data, method='POST')
        req.add_header('Authorization', f'Bearer {_agent_token(host_key)}')
        req.add_header('Content-Type', 'application/json')
        resp = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return resp.get('ok', False), resp.get('msg', resp.get('error', 'no msg'))
    except Exception as e:
        return False, str(e)

def _nc_diagnose_ssh(ip, name, source='docker'):
    """Legacy fallback: diagnose over SSH (port 22 is firewalled / root-login locked
    on most LXCs, so this usually fails — kept only as a last resort)."""
    if source == 'systemd':
        cmd = f'journalctl -u "{name}" -n 80 --no-pager 2>/dev/null'
    else:
        cmd = f'docker logs --tail=80 "{name}" 2>&1'
    out, err = _nc_ssh(ip, cmd, timeout=15)
    logs = (out + '\n' + err).strip()
    combined = logs.lower()
    for pattern, label, advice in _NC_DIAG_PATTERNS:
        if re.search(pattern, combined):
            return {'label': label, 'advice': advice, 'pattern': pattern,
                    'logs': logs[-1500:], 'ok': True}
    return {'label': 'Unbekannt', 'advice': 'Kein bekanntes Fehlermuster. Logs manuell prüfen.',
            'pattern': None, 'logs': logs[-1500:], 'ok': True}

def nc_diagnose(ip, name, source='docker'):
    """Diagnose a container/unit. Primary path = the gl-agent's /nanoclaw/diagnose
    endpoint (works without SSH); SSH is only a fallback. Fixes the perennial
    "auth error" on CT diag, which was caused by direct SSH to a firewalled port 22."""
    try:
        q = urllib.parse.urlencode({'container': name, 'source': source})
        req = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/nanoclaw/diagnose?{q}')
        req.add_header('Authorization', f'Bearer {GL_AGENT_TOKEN}')
        resp = json.loads(urllib.request.urlopen(req, timeout=12).read())
        return {'label':   resp.get('label', 'Unbekannt'),
                'advice':  resp.get('advice', ''),
                'pattern': resp.get('pattern'),
                'logs':    (resp.get('logs') or '')[-1500:],
                'ok':      resp.get('ok', True),
                'source':  'agent'}
    except Exception as agent_err:
        try:
            r = _nc_diagnose_ssh(ip, name, source=source)
            r['source'] = 'ssh'
            return r
        except Exception as ssh_err:
            return {'label': 'Fehler', 'pattern': None, 'logs': '', 'ok': False,
                    'advice': f'Agent nicht erreichbar ({agent_err}); SSH-Fallback fehlgeschlagen ({ssh_err}).'}

def _nc_disk_cleanup(host_key, ip):
    try:
        out, _ = _nc_ssh(ip,
            'docker system prune -f 2>&1 | tail -5 && '
            'journalctl --vacuum-size=150M 2>&1 | tail -3',
            timeout=60)
        return True, out[:300]
    except Exception as e:
        return False, str(e)

def _nanoclaw_tick():
    live = cache.get('live')
    if not live:
        return

    for h in live.get('hosts', []):
        key    = h['key']
        ip     = h['ip']
        ct_id  = h.get('ct_id')
        status = h.get('status', 'unknown')
        agt    = h.get('agent') or {}

        if not ct_id:
            continue  # only agent-enabled hosts

        # ── Rule 1: GL Agent watchdog ──────────────────────
        if status == 'online' and not agt:
            if _nc_cooldown_ok(key, 'agent_restart', 120):
                try:
                    out, _ = _nc_ssh(ip,
                        'systemctl restart gl-agent 2>&1 && sleep 2 && systemctl is-active gl-agent',
                        timeout=15)
                    _nc_log(key, 'agent_restart',
                            f'GL Agent nicht erreichbar auf {ip}',
                            out or 'gestartet', 'warn')
                except Exception as e:
                    _nc_log(key, 'agent_restart',
                            f'GL Agent offline auf {ip}', f'SSH-Fehler: {e}', 'error')

        if status != 'online' or not agt:
            continue

        # ── Rule 2: Disk cleanup ───────────────────────────
        disk_pct = (agt.get('disk') or {}).get('pct', 0) or 0
        if disk_pct > 88:
            if _nc_cooldown_ok(key, 'disk_cleanup', 3600):
                ok, msg = _nc_disk_cleanup(key, ip)
                _nc_log(key, 'disk_cleanup',
                        f'Disk {disk_pct}% auf {key} → prune + vacuum',
                        msg, 'warn' if ok else 'error')

        # ── Rule 3: Container crash → auto-restart ─────────
        docker_raw = cache.get(f'docker:{ip}', ttl=60)
        if not docker_raw:
            continue

        prev_ct = _nc_state.get(key, {}).get('containers', {})
        curr_ct = {}

        for ct in (docker_raw.get('containers') or []):
            ct_name = ct.get('name', '')
            is_up   = ct.get('status', '').lower().startswith('up')
            curr_ct[ct_name] = is_up

            if any(s in ct_name.lower() for s in _NC_NO_RESTART):
                continue

            if ct_name in prev_ct and prev_ct[ct_name] and not is_up:
                # Container went from up → down
                if _nc_cooldown_ok(key, f'restart:{ct_name}', 300):
                    diag = nc_diagnose(ip, ct_name)
                    ok, msg = _nc_agent_restart(key, ip, ct_name)
                    detail = f'{_clean_container_name(ct_name)} abgestürzt'
                    result = f'{"✓ neugestartet" if ok else "✗ FAILED"}: {msg} | Ursache: {diag["label"]}'
                    _nc_log(key, 'container_restart', detail, result,
                            'info' if ok else 'error')

        _nc_state.setdefault(key, {})['containers'] = curr_ct

def _nanoclaw_bg():
    # Sicherheit: automatisches Neustarten/Disk-Cleanup nur, wenn explizit aktiviert.
    # Default AUS — verhindert unueberwachte Eingriffe (Container-Restarts, prune/vacuum).
    if os.environ.get('NC_AUTO_RESTART', '0').lower() not in ('1', 'true', 'yes', 'on'):
        print('[Nanoclaw] AUTO-RESTART DEAKTIVIERT (NC_AUTO_RESTART=0) — nur Beobachtung')
        return
    time.sleep(30)  # wait for first live data to be available
    while True:
        try:
            _nanoclaw_tick()
        except Exception as e:
            print(f'[Nanoclaw] Tick error: {e}')
        time.sleep(60)

# ─── UNIFI ────────────────────────────────────
_unifi_cookie  = None
_unifi_csrf    = None
_unifi_expiry  = 0

_unifi_retry_at = 0

def _unifi_login():
    global _unifi_cookie, _unifi_csrf, _unifi_expiry, _unifi_retry_at
    if not UNIFI_URL or not UNIFI_USER:
        return False
    if time.time() < _unifi_retry_at:
        return False
    try:
        data = json.dumps({'username': UNIFI_USER, 'password': UNIFI_PASS}).encode()
        req  = urllib.request.Request(f'{UNIFI_URL}/api/auth/login',
                                      data=data, method='POST')
        req.add_header('Content-Type', 'application/json')
        resp = urllib.request.urlopen(req, context=_ssl_ctx, timeout=8)
        _unifi_cookie = resp.headers.get('Set-Cookie', '')
        _unifi_csrf   = resp.headers.get('X-CSRF-Token', '')
        _unifi_expiry = time.time() + 3500
        return True
    except Exception as e:
        _unifi_retry_at = time.time() + 600
        print(f'[UniFi] login failed: {e} (naechster Versuch in 10 min)')
        return False

def _unifi_get(path):
    global _unifi_cookie, _unifi_csrf, _unifi_expiry
    if time.time() > _unifi_expiry:
        if not _unifi_login():
            return None
    try:
        req = urllib.request.Request(f'{UNIFI_URL}/proxy/network/api/s/{UNIFI_SITE}{path}')
        req.add_header('Cookie', _unifi_cookie or '')
        if _unifi_csrf:
            req.add_header('X-CSRF-Token', _unifi_csrf)
        resp = urllib.request.urlopen(req, context=_ssl_ctx, timeout=8)
        return json.loads(resp.read()).get('data', [])
    except Exception as e:
        _unifi_expiry = 0  # force re-login next time
        return None

def get_unifi_data():
    cached = cache.get('unifi', ttl=30)
    if cached is not None:
        return cached

    clients = _unifi_get('/stat/sta') or []
    devices = _unifi_get('/stat/device') or []
    health  = _unifi_get('/stat/health') or []

    wan = {}
    for h in health:
        if h.get('subsystem') == 'wan':
            wan = {
                'rx_bytes': h.get('rx_bytes_r', 0),
                'tx_bytes': h.get('tx_bytes_r', 0),
                'latency':  h.get('latency', 0),
                'uptime':   h.get('uptime', 0),
                'status':   h.get('status', 'unknown'),
                'ip':       h.get('wan_ip', ''),
            }

    wlan_clients = [c for c in clients if not c.get('is_wired', True)]
    wired_clients = [c for c in clients if c.get('is_wired', True)]

    result = {
        'clients_total':  len(clients),
        'clients_wifi':   len(wlan_clients),
        'clients_wired':  len(wired_clients),
        'devices_total':  len(devices),
        'devices_online': sum(1 for d in devices if d.get('state') == 1),
        'wan':            wan,
        'top_clients':    sorted(
            [{'name': c.get('hostname') or c.get('name') or c.get('mac','?'),
              'ip':   c.get('ip',''),
              'mac':  c.get('mac',''),
              'rx':   c.get('rx_bytes',0),
              'tx':   c.get('tx_bytes',0),
              'rssi': c.get('rssi'),
              'type': 'wifi' if not c.get('is_wired') else 'wired'}
             for c in clients],
            key=lambda x: x['rx'] + x['tx'], reverse=True
        )[:20],
    }
    cache.set('unifi', result)
    return result

def _px_login():
    if not PROXMOX_HOST: return None
    global _px_ticket, _px_expiry
    now = time.time()
    if _px_ticket and _px_expiry > now + 60:
        return _px_ticket
    with _px_lock:
        if _px_ticket and _px_expiry > now + 60:
            return _px_ticket
        if not PROXMOX_PASS:
            return None
        try:
            data = urllib.parse.urlencode({'username': PROXMOX_USER, 'password': PROXMOX_PASS}).encode()
            req  = urllib.request.Request(f"{PROXMOX_API}/access/ticket", data=data)
            body = json.loads(urllib.request.urlopen(req, timeout=6, context=_ssl_ctx).read())
            _px_ticket = body['data']['ticket']
            _px_expiry = now + 7200
        except Exception as e:
            print(f'[PVE] Login: {e}')
            return None
        return _px_ticket

def _ensure_node():
    """Node-Namen automatisch bestimmen, wenn PROXMOX_NODE nicht gesetzt ist."""
    global PROXMOX_NODE
    if PROXMOX_NODE or not PROXMOX_HOST:
        return
    st = _px('/cluster/status')
    nodes = [n for n in (st or {}).get('data', []) if n.get('type') == 'node']
    local = [n for n in nodes if n.get('local')] or nodes
    if not local:
        nd = _px('/nodes')
        local = (nd or {}).get('data', [])
    if local:
        PROXMOX_NODE = local[0].get('name') or local[0].get('node') or ''

def _px(path):
    if not PROXMOX_HOST: return None
    if not PROXMOX_NODE and not path in ('/cluster/status', '/nodes'):
        _ensure_node()
    t = None if PROXMOX_TOKEN else _px_login()
    if not t and not PROXMOX_TOKEN: return None
    try:
        req = urllib.request.Request(f"{PROXMOX_API}{path}")
        if PROXMOX_TOKEN:
            req.add_header('Authorization', f'PVEAPIToken={PROXMOX_TOKEN}')
        else:
            req.add_header('Cookie', f'PVEAuthCookie={t}')
        return json.loads(urllib.request.urlopen(req, timeout=5, context=_ssl_ctx).read())
    except Exception:
        return None

# ─── AUTO-DISCOVERY ───────────────────────────

_lxc_ip_memory = {}   # vmid -> zuletzt bekannte IP (Proxmox liefert unter Last manchmal keine)

def discover_lxc_ips():
    cached = cache.get('lxc_ips', ttl=DISCOVERY_TTL)
    if cached is not None:
        return cached
    resp = _px(f'/nodes/{PROXMOX_NODE}/lxc')
    if not resp or 'data' not in resp:
        return {}
    result = {}
    for lxc in (resp.get('data') or []):
        vmid   = str(lxc.get('vmid', ''))
        name   = lxc.get('name', f'ct{vmid}')
        status = lxc.get('status', 'unknown')
        ip = None
        if status == 'running':
            ifaces = _px(f'/nodes/{PROXMOX_NODE}/lxc/{vmid}/interfaces')
            if ifaces and ifaces.get('data'):
                for iface in ifaces['data']:
                    if iface.get('name', '') == 'lo':
                        continue
                    inet = iface.get('inet', '')
                    if inet and '/' in inet:
                        candidate = inet.split('/')[0]
                        if candidate and not candidate.startswith('127.'):
                            ip = candidate
                            break
        if not ip and status == 'running':
            ip = _lxc_ip_memory.get(vmid)
            if not ip:
                for a in _agents_list():
                    if (a.get('hostname') or '').lower() == (name or '').lower():
                        ip = a['ip']; break
        if ip:
            _lxc_ip_memory[vmid] = ip
        result[vmid] = {'ip': ip, 'name': name, 'status': status}
    cache.set('lxc_ips', result)
    return result

def scan_ports_fast(ip, timeout=0.35):
    def probe(port):
        try:
            s = socket.socket(); s.settimeout(timeout)
            ok = s.connect_ex((ip, port)) == 0; s.close()
            return port if ok else None
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=24) as pool:
        return [p for p in pool.map(probe, SCAN_PORTS) if p]

def _manual_hosts_ensure():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('CREATE TABLE IF NOT EXISTS manual_hosts (key TEXT PRIMARY KEY, name TEXT, ip TEXT, created INTEGER)')
    conn.commit(); conn.close()

def sync_registry(lxc_ips=None):
    """Baut das Host-Register aus konfigurierter Infrastruktur, Agenten und manuellen Hosts."""
    if PROXMOX_HOST and 'proxmox' not in STATIC_HOSTS:
        STATIC_HOSTS['proxmox'] = ('Proxmox VE', PROXMOX_HOST, '🖥️', 'infra', None, [(8006, 'Proxmox Web', True, 'Hypervisor')])
    if UNIFI_URL and 'unifi' not in STATIC_HOSTS:
        uh = urllib.parse.urlparse(UNIFI_URL).hostname
        if uh:
            STATIC_HOSTS['unifi'] = ('UniFi', uh, '🌐', 'infra', None, [(443, 'UniFi Web UI', True, 'Netzwerk')])
    try:
        _manual_hosts_ensure()
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute('SELECT key,name,ip FROM manual_hosts').fetchall()
        conn.close()
        for k, n, ip in rows:
            STATIC_HOSTS.setdefault(k, (n, ip, '🖥️', 'app', None, []))
    except Exception as e:
        print(f'[registry] manual hosts: {e}')
    known = {v[1] for v in STATIC_HOSTS.values()}
    known |= {i.get('ip') for i in (lxc_ips or {}).values() if i.get('ip')}   # Proxmox-Container nicht doppelt als Agent-Host
    for a in _agents_list():
        if a['ip'] not in known:
            STATIC_HOSTS['agent-' + a['ip'].replace('.', '-')] = (a.get('hostname') or a['ip'], a['ip'], '🖥️', 'infra', None, [])
            known.add(a['ip'])

def run_discovery():
    cached = cache.get('discovery', ttl=DISCOVERY_TTL)
    if cached is not None:
        return cached

    lxc_ips    = discover_lxc_ips()
    sync_registry(lxc_ips)
    # Veraltete feste Eintraege entfernen: Container, die auf diesem Node nicht (mehr) laufen
    # oder eine andere IP haben, werden stattdessen aus Proxmox automatisch erkannt.
    if lxc_ips:
        for k, v in list(STATIC_HOSTS.items()):
            if v[4] is None:
                continue
            info = lxc_ips.get(str(v[4]))
            if not info or info['status'] != 'running' or (info.get('ip') and info['ip'] != v[1]):
                STATIC_HOSTS.pop(k, None)
    static_ips = {v[1] for v in STATIC_HOSTS.values()}
    ct_id_map  = {v[4]: k for k, v in STATIC_HOSTS.items() if v[4]}
    new_hosts  = []
    ip_updates = {}

    for vmid, info in lxc_ips.items():
        ip = info.get('ip')
        ct = int(vmid) if vmid.isdigit() else None

        if ct in ct_id_map:
            key = ct_id_map[ct]
            if ip and ip != STATIC_HOSTS[key][1]:
                ip_updates[key] = ip
            continue

        if ip in static_ips or not ip or info['status'] != 'running':
            continue

        open_ports = scan_ports_fast(ip)

        svcs = []
        for port in open_ports:
            nm, has_http = PORT_NAMES.get(port, (f':{port}', True))
            svcs.append((port, nm, has_http, 'auto-discovered'))

        STATIC_HOSTS[f'auto-ct{vmid}'] = (info['name'] or f'CT{vmid}', ip, '🔍', 'infra', ct, svcs)
        new_hosts.append({
            'key':      f'auto-ct{vmid}',
            'name':     info['name'] or f'CT{vmid}',
            'ip':       ip,
            'icon':     '🔍',
            'category': 'infra',
            'ct_id':    ct,
            'auto':     True,
            '_svcs':    svcs,
        })

    result = {'new_hosts': new_hosts, 'ip_updates': ip_updates,
              'lxc_map': lxc_ips, 'ts': int(time.time())}
    cache.set('discovery', result)
    return result

# ─── PROMETHEUS ───────────────────────────────

def get_prometheus():
    if not PROMETHEUS: return {}
    cached = cache.get('prom', ttl=10)
    if cached is not None:
        return cached
    def q(query):
        try:
            url  = f"{PROMETHEUS}/api/v1/query?query={urllib.parse.quote(query)}"
            return json.loads(urllib.request.urlopen(url, timeout=4).read()).get('data', {}).get('result', [])
        except Exception:
            return []
    m = {}
    for r in q('100-(avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[2m]))*100)'):
        ip = r['metric'].get('instance', '').split(':')[0]
        m.setdefault(ip, {})['cpu'] = round(float(r['value'][1]), 1)
    for r in q('(node_memory_MemTotal_bytes-node_memory_MemAvailable_bytes)/node_memory_MemTotal_bytes*100'):
        ip = r['metric'].get('instance', '').split(':')[0]
        m.setdefault(ip, {})['ram'] = round(float(r['value'][1]), 1)
    for r in q('rate(node_network_transmit_bytes_total{device!~"lo|docker.*|veth.*|br.*"}[2m])*8/1024/1024'):
        ip = r['metric'].get('instance', '').split(':')[0]
        m.setdefault(ip, {})['net_out'] = round(m.get(ip, {}).get('net_out', 0) + float(r['value'][1]), 2)
    for r in q('node_filesystem_avail_bytes{mountpoint="/"}/node_filesystem_size_bytes{mountpoint="/"} * 100'):
        ip = r['metric'].get('instance', '').split(':')[0]
        m.setdefault(ip, {})['disk_pct'] = round(100 - float(r['value'][1]), 1)
    cache.set('prom', m)
    return m

def get_loki_logs(query, limit=25):
    try:
        params = urllib.parse.urlencode({
            'query': query, 'limit': limit,
            'start': str(int((time.time() - 3600) * 1e9)),
            'direction': 'backward',
        })
        resp  = json.loads(urllib.request.urlopen(f"{LOKI_URL}/loki/api/v1/query_range?{params}", timeout=4).read())
        lines = []
        for stream in resp.get('data', {}).get('result', []):
            for ts, msg in stream.get('values', []):
                lines.append({'ts': int(ts) // int(1e9), 'msg': msg[:200]})
        lines.sort(key=lambda x: x['ts'], reverse=True)
        return lines[:limit]
    except Exception:
        return []

# ─── GL AGENT ─────────────────────────────────

def get_agent_data(ip, timeout=2):
    cached = cache.get(f'agent:{ip}', ttl=15)
    if cached is not None:
        return cached
    try:
        req = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/')
        req.add_header('Authorization', f'Bearer {_agent_token(ip)}')
        resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        cache.set(f'agent:{ip}', resp)
        return resp
    except Exception:
        cache.set(f'agent:{ip}', None)
        return None

def get_agent_docker(ip, timeout=2):
    cached = cache.get(f'docker:{ip}', ttl=20)
    if cached is not None:
        return cached
    try:
        req = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/docker')
        req.add_header('Authorization', f'Bearer {_agent_token(ip)}')
        result = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        cache.set(f'docker:{ip}', result)
        return result
    except Exception:
        cache.set(f'docker:{ip}', None)
        return None

# Nur echte Infra-Agenten ausblenden. Grafana/Prometheus/Loki sind
# nutzerseitige Dienste → NICHT skippen.
_DOCKER_SKIP = {
    'node-exporter', 'promtail',
    'dokploy-postgres', 'dokploy-redis', 'dokploy-traefik',
}

def _clean_container_name(raw):
    """Turn ugly Dokploy/swarm container names into readable display names."""
    n = raw
    n = re.sub(r'\.1\.[a-z0-9]+$', '', n)          # remove swarm task suffix
    n = re.sub(r'^(homelab|development|production|staging)-', '', n)  # strip env prefix
    n = re.sub(r'-[a-z0-9]{6,8}$', '', n)           # strip random suffix
    n = re.sub(r'-\d+$', '', n)                       # strip trailing index
    n = n.replace('-', ' ').strip().title()
    return n or raw

def docker_to_services(containers, ip, url_map):
    """Build service list from agent /docker response (dynamic discovery)."""
    # Internal: no exposed port
    SKIP_NO_PORT  = {'node-exporter', 'promtail'}
    svcs = []; ok = 0; total = 0
    seen_ports = set()
    seen_names = set()   # gegen Swarm-Replikas (gleicher Service mehrfach)
    for ct in (containers or []):
        raw_name  = ct.get('name', '')
        source    = ct.get('source', 'docker')
        # Systemd services are only for the detail panel, not service count/status
        if source == 'systemd':
            continue
        # Skip infra-internal containers
        if any(s in raw_name.lower() for s in _DOCKER_SKIP):
            continue
        st_lower = ct.get('status', '').lower()
        is_up = st_lower.startswith('up') or 'running' in st_lower
        # Bewusst gestoppte Container (Exited/Created) sind keine Stoerung; nur
        # Neustart-Schleifen, "dead" und "unhealthy" zaehlen als Ausfall.
        is_stopped = not is_up and (st_lower.startswith('exited') or st_lower.startswith('created'))
        if 'unhealthy' in st_lower:
            is_up = False
        ports_str  = ct.get('ports', '')
        host_ports = re.findall(r'(?:0\.0\.0\.0|::):(\d+)->', ports_str)
        display    = _clean_container_name(raw_name)
        image_hint = (ct.get('image') or '').split(':')[0].split('/')[-1]

        if not host_ports:
            # Only show containers with no exposed ports if they're user-visible services
            # Skip internal DBs, monitoring agents, and anything in the skip lists
            if any(s in raw_name.lower() for s in SKIP_NO_PORT):
                continue
            # Also skip obvious internal containers (postgres, redis, etc.)
            if any(s in raw_name.lower() for s in ('postgres', 'redis', 'mysql', 'mariadb',
                                                     'mongo', 'rabbitmq', 'memcached')):
                continue
            if display.lower() in seen_names:   # Replika bereits gelistet
                continue
            seen_names.add(display.lower())
            if is_stopped:
                svcs.append({'name': display, 'port': 0, 'status': 'stopped', 'rtt': None, 'code': None,
                             'url': None, 'desc': image_hint, 'dynamic': True})
                continue
            total += 1
            if is_up: ok += 1
            svcs.append({'name': display, 'port': 0,
                         'status': 'online' if is_up else 'offline',
                         'rtt': None, 'code': None, 'url': None,
                         'desc': image_hint, 'dynamic': True})
        else:
            for hp in host_ports:
                port = int(hp)
                if port in seen_ports:
                    continue
                seen_ports.add(port)
                svc_url = url_map.get(display) or f'http://{ip}:{port}'
                if is_stopped:
                    svcs.append({'name': display, 'port': port, 'status': 'stopped', 'rtt': None, 'code': None,
                                 'url': svc_url, 'desc': image_hint, 'dynamic': True})
                    continue
                total += 1
                if is_up: ok += 1
                svcs.append({'name': display, 'port': port,
                             'status': 'online' if is_up else 'offline',
                             'rtt': None, 'code': None, 'url': svc_url,
                             'desc': image_hint, 'dynamic': True})
    return svcs, ok, total

def get_agent_logs(ip, timeout=3):
    try:
        req = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/logs')
        req.add_header('Authorization', f'Bearer {_agent_token(ip)}')
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception:
        return None

def get_agent_nc_events(ip, timeout=3):
    try:
        req = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/nanoclaw/events')
        req.add_header('Authorization', f'Bearer {_agent_token(ip)}')
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception:
        return None

# ─── PROXMOX STATUS ───────────────────────────

def get_proxmox_status():
    cached = cache.get('prox_stat', ttl=10)
    if cached:
        return cached
    result = {'online': False, 'cpu': 0, 'ram_pct': 0, 'ram_used_gb': 0,
              'ram_total_gb': 0, 'uptime_h': 0, 'lxc_running': 0, 'lxc_total': 0, 'lxcs': []}
    nd = _px(f'/nodes/{PROXMOX_NODE}/status')
    if nd and 'data' in nd:
        d = nd['data']
        result['online'] = True
        result['cpu']    = round(float(d.get('cpu', 0)) * 100, 1)
        mem = d.get('memory', {})
        mu  = int(mem.get('used', 0)); mt = int(mem.get('total', 1))
        result['ram_used_gb']  = round(mu / (1024**3), 1)
        result['ram_total_gb'] = round(mt / (1024**3), 1)
        result['ram_pct']      = round(mu / mt * 100, 1) if mt else 0
        result['uptime_h']     = round(int(d.get('uptime', 0)) / 3600, 1)
    lxcs = _px(f'/nodes/{PROXMOX_NODE}/lxc')
    if lxcs and 'data' in lxcs:
        ld = lxcs['data']
        result['lxc_running'] = sum(1 for c in ld if c.get('status') == 'running')
        result['lxc_total']   = len(ld)
        result['lxcs']        = [{'id': c.get('vmid'), 'name': c.get('name', ''),
                                   'status': c.get('status', '')} for c in ld]
    cache.set('prox_stat', result)
    return result

def get_cluster_resources():
    """Autoritative Live-Daten pro Container aus Proxmox /cluster/resources.
    Matcht das Proxmox-Dashboard 1:1 → einzige Wahrheit für CT-CPU/RAM/Status.
    Rückgabe: {vmid: {status, cpu_pct, mem_pct, mem_used_gb, mem_total_gb, uptime}}"""
    cached = cache.get('cluster_res', ttl=10)
    if cached is not None:
        return cached
    out = {}
    d = _px('/cluster/resources?type=vm')
    if d and 'data' in d:
        for r in (d.get('data') or []):
            if r.get('node') != PROXMOX_NODE:
                continue
            vmid = r.get('vmid')
            if vmid is None:
                continue
            mem  = int(r.get('mem') or 0)
            mmax = int(r.get('maxmem') or 0)
            out[vmid] = {
                'status':       r.get('status', 'unknown'),
                'cpu_pct':      round(float(r.get('cpu') or 0) * 100, 1),
                'mem_pct':      round(mem / mmax * 100, 1) if mmax else 0,
                'mem_used_gb':  round(mem / (1024**3), 2),
                'mem_total_gb': round(mmax / (1024**3), 2),
                'uptime':       int(r.get('uptime') or 0),
            }
    cache.set('cluster_res', out)
    return out

# ─── ASSET INVENTORY (OS / Python / packages per LXC) ──────────
# Collected via the Proxmox host (`pct exec`) so no agent change is needed.
# Enables zero-day triage: "which CT runs package X (version Y)?".

_INV_SCRIPT = (
    'echo "###OS"; grep -E "^(PRETTY_NAME|VERSION_ID|ID)=" /etc/os-release 2>/dev/null; '
    'echo "###PY"; python3 --version 2>&1; '
    'echo "###KERNEL"; uname -r; '
    'echo "###PKGS"; dpkg-query -W 2>/dev/null; '
    'echo "###PIP"; pip3 list --format=freeze 2>/dev/null | head -400'
)

def _prox_exec(vmid, cmd, timeout=40):
    """Run a command inside an LXC via the Proxmox host (pct exec)."""
    ssh = _paramiko.SSHClient()
    ssh.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
    ssh.connect(PROXMOX_HOST, port=22, username='root', password=PROXMOX_PASS,
                timeout=10, look_for_keys=False, allow_agent=False)
    try:
        _, o, e = ssh.exec_command(f"pct exec {int(vmid)} -- sh -c '{cmd}'", timeout=timeout)
        return o.read().decode('utf-8', 'replace') + e.read().decode('utf-8', 'replace')
    finally:
        ssh.close()

def _inv_ensure_table():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS inventory (
        host_key TEXT PRIMARY KEY, vmid INTEGER, os TEXT, version_id TEXT,
        python TEXT, kernel TEXT, pkg_count INTEGER, packages_json TEXT, scanned_at INTEGER)''')
    conn.commit(); conn.close()

def _parse_inventory(raw):
    section = None
    info = {'os': '', 'version_id': '', 'distro': '', 'python': '', 'kernel': '', 'packages': {}}
    for line in raw.splitlines():
        if line.startswith('###'):
            section = line[3:]; continue
        if section == 'OS':
            if line.startswith('PRETTY_NAME='): info['os'] = line.split('=', 1)[1].strip().strip('"')
            elif line.startswith('VERSION_ID='): info['version_id'] = line.split('=', 1)[1].strip().strip('"')
            elif line.startswith('ID='): info['distro'] = line.split('=', 1)[1].strip().strip('"')
        elif section == 'PY' and line.strip():
            info['python'] = line.replace('Python', '').strip() or info['python']
        elif section == 'KERNEL' and line.strip():
            info['kernel'] = line.strip()
        elif section == 'PKGS' and line.strip():
            parts = line.split('\t')
            if len(parts) >= 2:
                info['packages'][parts[0].split(':')[0]] = parts[1].strip()
        elif section == 'PIP' and '==' in line:
            n, _, v = line.partition('==')
            if n.strip():
                info['packages']['pip:' + n.strip()] = v.strip()
    info['pkg_count'] = len(info['packages'])
    return info

def scan_host_inventory(host_key):
    h = STATIC_HOSTS.get(host_key)
    vmid = h[4] if h else None
    if not vmid:
        live = cache.get('live')
        hobj = next((x for x in (live or {}).get('hosts', []) if x['key'] == host_key), None) if live else None
        vmid = hobj.get('ct_id') if hobj else None
    if not vmid:
        return {'ok': False, 'error': 'Kein LXC / keine VMID'}
    if not PROXMOX_PASS:
        return {'ok': False, 'error': 'PROXMOX_PASS nicht gesetzt'}
    try:
        inv = _parse_inventory(_prox_exec(vmid, _INV_SCRIPT, timeout=45))
        _inv_ensure_table()
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('''INSERT INTO inventory
            (host_key,vmid,os,version_id,python,kernel,pkg_count,packages_json,scanned_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(host_key) DO UPDATE SET vmid=excluded.vmid, os=excluded.os,
            version_id=excluded.version_id, python=excluded.python, kernel=excluded.kernel,
            pkg_count=excluded.pkg_count, packages_json=excluded.packages_json,
            scanned_at=excluded.scanned_at''',
            (host_key, vmid, inv['os'], inv['version_id'], inv['python'], inv['kernel'],
             inv['pkg_count'], json.dumps(inv['packages']), int(time.time())))
        conn.commit(); conn.close()
        inv.update({'ok': True, 'host_key': host_key, 'vmid': vmid, 'scanned_at': int(time.time())})
        return inv
    except Exception as e:
        return {'ok': False, 'error': str(e)}

def _inv_all_summary():
    _inv_ensure_table()
    conn = sqlite3.connect(AUDIT_DB)
    rows = conn.execute('SELECT host_key,vmid,os,version_id,python,kernel,pkg_count,scanned_at FROM inventory').fetchall()
    conn.close()
    return [{'host_key': r[0], 'vmid': r[1], 'os': r[2], 'version_id': r[3],
             'python': r[4], 'kernel': r[5], 'pkg_count': r[6], 'scanned_at': r[7]} for r in rows]

def _inv_os_map():
    """{host_key: real distro OS} from the inventory (so the UI shows e.g. 'Ubuntu
    24.04' instead of the shared Proxmox kernel that the agent reports as OS)."""
    cached = cache.get('inv_os', ttl=300)
    if cached is not None:
        return cached
    m = {}
    try:
        _inv_ensure_table()
        conn = sqlite3.connect(AUDIT_DB)
        m = {r[0]: r[1] for r in conn.execute('SELECT host_key, os FROM inventory').fetchall()}
        conn.close()
    except Exception:
        pass
    cache.set('inv_os', m)
    return m

# ─── LXC LIFECYCLE (start/stop/reboot whole container via Proxmox) ──
def _prox_host_exec(cmd, timeout=60):
    ssh = _paramiko.SSHClient()
    ssh.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
    ssh.connect(PROXMOX_HOST, port=22, username='root', password=PROXMOX_PASS,
                timeout=10, look_for_keys=False, allow_agent=False)
    try:
        _, o, e = ssh.exec_command(cmd, timeout=timeout)
        return o.read().decode('utf-8', 'replace') + e.read().decode('utf-8', 'replace')
    finally:
        ssh.close()

def lxc_action(host_key, action):
    if action not in ('start', 'stop', 'reboot', 'shutdown'):
        return {'ok': False, 'error': 'Ungültige Aktion'}
    vmid = _host_vmid(host_key)
    if not vmid:
        return {'ok': False, 'error': 'Kein LXC / keine VMID'}
    if not PROXMOX_PASS:
        return {'ok': False, 'error': 'PROXMOX_PASS fehlt'}
    try:
        out = _prox_host_exec(f'pct {action} {int(vmid)} 2>&1', timeout=90).strip()
        ok = 'error' not in out.lower() and 'unable' not in out.lower() and 'failed' not in out.lower()
        cache.bust()
        return {'ok': ok, 'msg': out[:300] or f'{action} ausgelöst'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

# ─── CONTAINER ACTIONS (start/stop/restart via Proxmox) ────────
_SAFE_CNAME = re.compile(r'^[A-Za-z0-9_.\-]+$')

def _host_vmid(host_key):
    h = STATIC_HOSTS.get(host_key)
    if h and h[4]:
        return h[4]
    live = cache.get('live')
    hobj = next((x for x in (live or {}).get('hosts', []) if x['key'] == host_key), None) if live else None
    return hobj.get('ct_id') if hobj else None

def container_action(host_key, name, action):
    if action not in ('start', 'stop', 'restart'):
        return {'ok': False, 'error': 'Ungültige Aktion'}
    if not name or not _SAFE_CNAME.match(name):
        return {'ok': False, 'error': 'Ungültiger Container-Name'}
    ip = _host_ip(host_key)
    if ip:
        r = _agent_call(ip, '/docker/action', {'name': name, 'action': action})
        err = r.get('error') or ''
        if r.get('ok') or (err and err != 'Not found' and not err.startswith('Agent nicht erreichbar')):
            cache.bust()
            return r
    vmid = _host_vmid(host_key)
    if not vmid:
        return {'ok': False, 'error': 'Kein Agent erreichbar und kein LXC'}
    try:
        out = _prox_exec(vmid, f'docker {action} {name} 2>&1', timeout=45).strip()
        ok = 'error' not in out.lower() and 'no such' not in out.lower()
        cache.bust()
        return {'ok': ok, 'msg': out[:300] or f'{action} ok'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

# ─── CHECKS ───────────────────────────────────

def _tcp(host, port, timeout=3):
    try:
        s = socket.socket(); s.settimeout(timeout)
        ok = s.connect_ex((host, port)) == 0; s.close()
        return ok
    except Exception:
        return False

def _http(url, timeout=5):
    try:
        start = time.time()
        req   = urllib.request.Request(url)
        ctx   = _ssl_ctx if url.startswith('https') else None
        resp  = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        rtt   = round((time.time() - start) * 1000, 1)
        return (resp.status, rtt, True)
    except urllib.request.HTTPError as e:
        return (e.code, None, 100 <= e.code < 500)
    except Exception:
        return (None, None, False)

def _ping(host):
    try:
        start = time.time()
        r = subprocess.run(['ping', '-c', '1', '-W', '2', host],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            m = re.search(r'time=([0-9.]+)\s*ms', r.stdout)
            return (float(m.group(1)) if m else round((time.time()-start)*1000, 1), True)
    except Exception:
        pass
    for port in (443, 80, 22, 8080, 8006, 3000):
        try:
            s = socket.socket(); s.settimeout(0.7)
            t0 = time.time()
            if s.connect_ex((host, port)) == 0:
                s.close()
                return (round((time.time()-t0)*1000, 1), True)
            s.close()
        except Exception:
            continue
    return (None, False)

def _record_ping(key, rtt, ok):
    with ph_lock:
        if key not in ping_history:
            ping_history[key] = []
        ping_history[key].append({'t': int(time.time()), 'rtt': rtt, 'ok': ok})
        if len(ping_history[key]) > 60:
            ping_history[key] = ping_history[key][-60:]

def _get_ph(key, n=20):
    with ph_lock:
        return ping_history.get(key, [])[-n:]

# ─── LIVE CHECKS ──────────────────────────────

def run_live_checks():
    cached = cache.get('live', ttl=CACHE_TTL)
    if cached:
        return cached

    prom = get_prometheus()
    prox = get_proxmox_status()
    cres = get_cluster_resources()   # autoritative per-CT Live-Daten
    disc = run_discovery()

    # Merge auto-discovered hosts
    effective = dict(STATIC_HOSTS)
    for ah in disc.get('new_hosts', []):
        key = ah['key']
        if key not in effective:
            effective[key] = (ah['name'], ah['ip'], ah['icon'], ah['category'], ah['ct_id'], ah.get('_svcs', []))

    for key, new_ip in disc.get('ip_updates', {}).items():
        if key in effective:
            h = list(effective[key]); h[1] = new_ip; effective[key] = tuple(h)

    with ThreadPoolExecutor(max_workers=48) as pool:
        futures = {}
        # Hosts with GL agent installed (LXCs + CasaOS)
        agent_ips = {a['ip'] for a in _agents_list()}
        for key, (name, ip, icon, cat, ct_id, services) in effective.items():
            futures[pool.submit(_ping, ip)] = f'ping:{key}'
            if ct_id or ip in agent_ips:
                futures[pool.submit(get_agent_data, ip)] = f'agent:{key}'
                futures[pool.submit(get_agent_docker, ip)] = f'docker:{key}'
            for port, svc_name, has_http, desc in services:
                if port > 0 and has_http:
                    scheme = 'https' if port in (443, 8443, 9443, 8006) else 'http'
                    futures[pool.submit(_http, f'{scheme}://{ip}:{port}')] = f'http:{key}:{svc_name}'
                elif port > 0:
                    futures[pool.submit(_tcp, ip, port)] = f'port:{key}:{svc_name}'
        results = {}
        for f in as_completed(futures):
            try:
                results[futures[f]] = f.result()
            except Exception:
                pass

    hosts_data = []
    summary    = {'total': 0, 'online': 0, 'offline': 0, 'degraded': 0}

    for key, (name, ip, icon, cat, ct_id, services) in effective.items():
        pr   = results.get(f'ping:{key}')
        prtt = pr[0] if pr and pr[1] else None
        pok  = pr[1] if pr else False
        _record_ping(key, prtt, pok)

        svcs = []; svc_ok = 0; svc_total = 0
        url_map  = SERVICE_URLS.get(key, {})
        has_agent = bool(ct_id or ip in agent_ips)
        docker_raw = results.get(f'docker:{key}')

        if has_agent and docker_raw and docker_raw.get('containers'):
            # Dynamic: derive services from running docker containers
            svcs, svc_ok, svc_total = docker_to_services(
                docker_raw['containers'], ip, url_map)
        else:
            # Static fallback: check hardcoded port list
            for port, svc_name, has_http, desc in services:
                if svc_name == 'Node Exporter':
                    continue
                svc_total += 1
                svc_url    = url_map.get(svc_name)
                if has_http and port > 0:
                    r = results.get(f'http:{key}:{svc_name}')
                    if r and r[2]:
                        svc_ok += 1
                        svcs.append({'name': svc_name, 'port': port, 'status': 'online',   'rtt': r[1], 'code': r[0], 'url': svc_url, 'desc': desc})
                    elif r:
                        svcs.append({'name': svc_name, 'port': port, 'status': 'degraded', 'rtt': r[1], 'code': r[0], 'url': svc_url, 'desc': desc})
                    else:
                        svcs.append({'name': svc_name, 'port': port, 'status': 'offline',  'rtt': None, 'code': None, 'url': svc_url, 'desc': desc})
                elif port > 0:
                    ok2 = results.get(f'port:{key}:{svc_name}', False)
                    if ok2: svc_ok += 1
                    svcs.append({'name': svc_name, 'port': port, 'status': 'online' if ok2 else 'offline', 'rtt': None, 'code': None, 'url': svc_url, 'desc': desc})

        # ── Status: Proxmox ist die Wahrheit für CTs ──────────────────────
        # Ein laufender CT wird NIE faelschlich "offline" gezeigt, nur weil
        # ICMP/Port-Checks scheitern. Nicht-CT-Hosts gelten als erreichbar,
        # wenn Ping ODER irgendein Service antwortet.
        cres_status = cres.get(ct_id, {}).get('status') if ct_id else None
        reason = ''
        if cres_status is not None:
            if cres_status != 'running':
                st, reason = 'offline', f'Proxmox: {cres_status}'
            elif svc_total > 0 and svc_ok == 0:
                st, reason = 'degraded', 'läuft, aber kein Service erreichbar'
            elif svc_total > 0 and svc_ok < svc_total:
                st, reason = 'degraded', f'{svc_ok}/{svc_total} Services online'
            else:
                st = 'online'
        else:
            reachable = pok or svc_ok > 0
            st = 'online' if reachable else 'offline'
            if not reachable:
                reason = 'nicht erreichbar (Ping + Ports)'
            elif svc_total > 0 and svc_ok == 0:
                st, reason = ('online', '') if pok else ('offline', 'keine Services')
            elif svc_total > 0 and svc_ok < svc_total:
                st, reason = 'degraded', f'{svc_ok}/{svc_total} Services online'

        summary['total'] += 1
        summary[st if st in summary else 'offline'] += 1

        pm  = prom.get(ip, {})
        agt = results.get(f'agent:{key}')
        cr  = cres.get(ct_id, {}) if ct_id else {}
        # CPU/RAM: Proxmox (autoritativ) > Prometheus > None. Nie erfinden.
        cpu_val = cr.get('cpu_pct') if cr else pm.get('cpu')
        ram_val = cr.get('mem_pct') if cr else pm.get('ram')
        cpu_src = 'proxmox' if cr else ('prometheus' if pm.get('cpu') is not None else None)
        hosts_data.append({
            'key':          key,
            'name':         name,
            'ip':           ip,
            'icon':         icon,
            'category':     cat,
            'ct_id':        ct_id,
            'auto':         key.startswith('auto-'),
            'os_name':      _inv_os_map().get(key),
            'status':       st,
            'status_reason': reason,
            'ping_rtt':     prtt,
            'ping_history': _get_ph(key, 20),
            'services':     svcs,
            'svc_online':   svc_ok,
            'svc_total':    svc_total,
            'metrics':      {'cpu': cpu_val, 'ram': ram_val,
                             'net_out': pm.get('net_out'),
                             'disk_pct': pm.get('disk_pct'),
                             'uptime': cr.get('uptime'),
                             'mem_used_gb': cr.get('mem_used_gb'),
                             'mem_total_gb': cr.get('mem_total_gb'),
                             'source': cpu_src},
            'agent':        agt,
        })

    # Build topology for flow diagram
    topology = {}
    for h in hosts_data:
        topology[h['key']] = {
            'label':   f"{h['icon']} {h['name']}",
            'ip':      h['ip'],
            'status':  h['status'],
            'ct_id':   h['ct_id'],
            'parent':  None,
        }
    topology['_internet'] = {'label': '🌍 Internet', 'ip': None, 'status': 'online', 'parent': None}
    root = 'unifi' if 'unifi' in topology else '_internet'
    if 'unifi' in topology:
        topology['unifi']['parent'] = '_internet'
    if 'proxmox' in topology:
        topology['proxmox']['parent'] = root
    for k, t in topology.items():
        if k in ('_internet', 'unifi', 'proxmox'):
            continue
        t['parent'] = 'proxmox' if ('proxmox' in topology and t.get('ct_id')) else root

    # ── Alert generation ──────────────────────────
    thr = _get_thresholds()
    active_alerts = []
    seen_hosts = set()
    for h in hosts_data:
        key    = h['key']
        name   = h['name']
        ip     = h['ip']
        m      = h.get('metrics') or {}
        ag     = h.get('agent') or {}
        status = h.get('status', 'unknown')

        if status == 'offline' and key not in seen_hosts:
            active_alerts.append({'severity': 'critical', 'key': key, 'host': name, 'ip': ip,
                                   'msg': 'Host offline', 'ts': int(time.time())})
            seen_hosts.add(key)

        # Autoritative Werte (Proxmox/Prometheus) vor Agent-Werten — konsistent mit Anzeige
        cpu = (m.get('cpu') if m.get('cpu') is not None else ag.get('cpu_pct', 0)) or 0
        mem = (m.get('ram') if m.get('ram') is not None else ag.get('mem_pct', 0)) or 0
        dsk = (ag.get('disk') or {}).get('pct', 0) or 0

        if cpu > thr['cpu_warn']:
            active_alerts.append({'severity': 'warn', 'key': key, 'host': name, 'ip': ip,
                                   'msg': f'CPU {cpu:.0f}%', 'ts': int(time.time())})
        if mem > thr['ram_warn']:
            active_alerts.append({'severity': 'warn', 'key': key, 'host': name, 'ip': ip,
                                   'msg': f'RAM {mem:.0f}%', 'ts': int(time.time())})
        if dsk > thr['disk_crit']:
            active_alerts.append({'severity': 'critical', 'key': key, 'host': name, 'ip': ip,
                                   'msg': f'Disk {dsk}%', 'ts': int(time.time())})

    # ── Enrich hosts with SLA / predictive / SSL ──────────────────────────
    ssl_data = {}
    try: ssl_data = get_ssl_all()
    except Exception: pass

    now_ts = int(time.time())
    for h in hosts_data:
        hkey = h['key']
        h['sla_30d']       = get_sla_pct(hkey)
        h['disk_pred_days'] = predict_days_until(hkey, 'disk', 90.0)
        smap      = ssl_data.get(hkey, {})
        days_vals = [v['days_left'] for v in smap.values()
                     if isinstance(v, dict) and v.get('days_left') is not None]
        h['ssl_min_days'] = min(days_vals) if days_vals else None
        if h['disk_pred_days'] is not None and h['disk_pred_days'] < 14:
            active_alerts.append({'severity': 'predict', 'key': hkey,
                                   'host': h['name'], 'ip': h['ip'],
                                   'msg': f'Disk voll in ~{h["disk_pred_days"]}d', 'ts': now_ts})
        if h['ssl_min_days'] is not None and h['ssl_min_days'] < thr['ssl_warn_days']:
            sev = 'critical' if h['ssl_min_days'] < 7 else 'warn'
            active_alerts.append({'severity': sev, 'key': hkey,
                                   'host': h['name'], 'ip': h['ip'],
                                   'msg': f'SSL läuft in {h["ssl_min_days"]}d ab', 'ts': now_ts})

    # ── Telegram notifications ─────────────────────────────────────────────
    try: _tg_check_alerts(hosts_data)
    except Exception: pass

    # Apply host_meta overrides (editable categories/names from settings)
    meta_overrides = _get_host_meta()
    for h in hosts_data:
        m = meta_overrides.get(h['key'], {})
        if m.get('category'):
            h['category'] = m['category']
        if m.get('display_name'):
            h['name'] = m['display_name']
        h['notes'] = m.get('notes', '')

    unifi   = get_unifi_data() or {}
    litellm = get_litellm_status() or {}
    dokploy = get_dokploy_apps() or {}

    result = {
        'timestamp':      int(time.time()),
        'summary':        summary,
        'proxmox':        prox,
        'unifi':          unifi,
        'litellm':        litellm,
        'dokploy':        dokploy,
        'hosts':          hosts_data,
        'topology':       topology,
        'external':       EXTERNAL_LINKS,
        'prom_ok':        bool(prom),
        'discovery_ts':   disc.get('ts'),
        'new_host_count': len(disc.get('new_hosts', [])),
        'alerts':         active_alerts,
        'alert_count':    len(active_alerts),
    }
    cache.set('live', result)
    return result

def _bg():
    while True:
        try:
            cache.bust('live'); cache.bust('prox_stat'); cache.bust('prom')
            run_live_checks()
        except Exception as e:
            print(f'[BG] {e}')
        time.sleep(CACHE_TTL)

# ─── ROUTES ───────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if session.get('authenticated'):
        return redirect(url_for('index'))
    if _user_count() == 0:
        return redirect(url_for('setup_page'))
    error = None
    if request.method == 'POST':
        ip = request.remote_addr or '?'
        if _login_blocked(ip):
            _audit('?', 'login_blocked', '', f'zu viele Fehlversuche · {ip}')
            return render_template('login.html',
                error=f'Zu viele Fehlversuche — gesperrt für {LOGIN_BLOCK_S // 60} Minuten'), 429
        # ── MFA step 2: a pending user submits their TOTP code ──
        if session.get('mfa_pending'):
            u = session['mfa_pending']
            code = request.form.get('mfa_code', '').strip()
            um = _user_mfa(u)
            try:
                import pyotp
                valid = bool(um and um['secret'] and pyotp.TOTP(um['secret']).verify(code, valid_window=1))
            except Exception:
                valid = False
            if valid:
                _login_fail_clear(ip)
                _login_finalize(u, (_user_get(u) or {}).get('role', 'admin'))
                return redirect(url_for('index'))
            _login_fail_register(ip)
            _audit(u or '?', 'login_fail', '', f'2FA falsch · {request.remote_addr or ""}')
            return render_template('login.html', error='Falscher 2FA-Code', mfa=True)

        # ── step 1: username + password ──
        if OIDC_ONLY and oidc_enabled():
            return render_template('login.html', error='Anmeldung nur über SSO'), 403
        u = request.form.get('username', '').strip().lower()
        p = request.form.get('password', '')
        ok, role = False, 'admin'
        dbu = _user_get(u)
        if dbu and check_password_hash(dbu['pw_hash'], p):
            ok, role = True, dbu['role'] or 'viewer'
        elif u in USERS and check_password_hash(USERS[u], p):  # safety-net fallback (always admin)
            ok, role = True, 'admin'
        if ok:
            _login_fail_clear(ip)
            um = _user_mfa(u)
            if um and um['enabled'] and um['secret']:
                session.clear()
                session['mfa_pending'] = u
                session.permanent = True
                return render_template('login.html', error=None, mfa=True)
            _login_finalize(u, role)
            return redirect(url_for('index'))
        _login_fail_register(ip)
        _audit(u or '?', 'login_fail', '', f'falsche Zugangsdaten · {request.remote_addr or ""}')
        error = 'Ungültige Zugangsdaten'
    return render_template('login.html', error=error, username=(request.form.get('username', '') if request.method == 'POST' else '')[:64])

@app.route('/logout')
def logout():
    try:
        if session.get('username'):
            _audit(session.get('username'), 'logout', '', request.remote_addr or '')
    except Exception:
        pass
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/healthz')
def healthz():
    """Öffentlicher Health-Check für Uptime-Monitoring (kein Login nötig)."""
    live = cache.get('live', ttl=86400) or {}
    age = int(time.time() - live['timestamp']) if live.get('timestamp') else None
    return jsonify({'ok': True, 'version': APP_VERSION, 'live_age_s': age})

@app.route('/api/public/status')
def api_public_status():
    if not PUBLIC_STATUS:
        return jsonify({'error': 'disabled'}), 404
    live = cache.get('live', ttl=90)
    if live is None:
        live = run_live_checks()
    hosts = [{'name': h.get('name', '?'), 'category': h.get('category', ''),
              'status': h.get('status', 'unknown')} for h in live.get('hosts', [])]
    online = sum(1 for h in hosts if h['status'] == 'online')
    return jsonify({'updated': live.get('timestamp'), 'total': len(hosts),
                    'online': online, 'hosts': hosts})

_STATUS_HTML = '''<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Status</title><style>
body{margin:0;font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3}
.wrap{max-width:720px;margin:0 auto;padding:32px 16px}
h1{font-size:20px;display:flex;align-items:center;gap:10px}
.banner{padding:14px 18px;border-radius:10px;margin:18px 0;font-weight:600}
.banner.ok{background:#0f2e1d;color:#3fb950;border:1px solid #1f6f3d}
.banner.warn{background:#3a2d0c;color:#d29922;border:1px solid #9e7c1a}
.svc{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid #21262d}
.svc:last-child{border-bottom:none}
.list{background:#161b22;border:1px solid #21262d;border-radius:10px}
.pill{font-size:12px;padding:3px 10px;border-radius:99px;font-weight:600}
.pill.online{background:#0f2e1d;color:#3fb950}.pill.offline{background:#3d1418;color:#f85149}
.pill.unknown{background:#21262d;color:#8b949e}
.cat{color:#8b949e;font-size:12px;margin-left:8px}
.foot{color:#8b949e;font-size:12px;margin-top:16px}
</style></head><body><div class="wrap">
<h1>System Status</h1>
<div id="banner" class="banner ok">Lade …</div>
<div id="list" class="list"></div>
<div class="foot" id="foot"></div>
<script>
async function load(){
  try{
    const d = await (await fetch('/api/public/status')).json();
    const b = document.getElementById('banner');
    const down = d.total - d.online;
    if(down === 0){ b.className='banner ok'; b.textContent='✓ Alle Systeme betriebsbereit ('+d.online+'/'+d.total+')'; }
    else { b.className='banner warn'; b.textContent='⚠ '+down+' von '+d.total+' Diensten gestört'; }
    document.getElementById('list').innerHTML = (d.hosts||[]).map(h =>
      '<div class="svc"><span>'+h.name+'<span class="cat">'+(h.category||'')+'</span></span>'+
      '<span class="pill '+h.status+'">'+(h.status==='online'?'betriebsbereit':h.status==='offline'?'gestört':'unbekannt')+'</span></div>').join('');
    document.getElementById('foot').textContent = 'Stand: '+new Date((d.updated||0)*1000).toLocaleString();
  }catch(e){ document.getElementById('banner').textContent='Status derzeit nicht verfügbar'; }
}
load(); setInterval(load, 30000);
</script></div></body></html>'''

@app.route('/status')
def status_page():
    if not PUBLIC_STATUS:
        return redirect(url_for('login_page'))
    return _STATUS_HTML

@app.route('/')
@login_required
def index():
    # New React SPA (Vite build) lives in static/spa. Falls back to the legacy
    # template if the build isn't present (e.g. local dev without a frontend build).
    spa = os.path.join(app.static_folder, 'spa', 'index.html')
    if os.path.exists(spa):
        return send_from_directory(os.path.join(app.static_folder, 'spa'), 'index.html')
    return 'Frontend nicht gebaut: im Ordner frontend/ "npm install && npm run build" ausfuehren.', 503

@app.route('/api/live')
@login_required
def api_live():
    return jsonify(run_live_checks())

@app.route('/api/prometheus')
@login_required
def api_prometheus():
    return jsonify(get_prometheus())

@app.route('/api/discovery/refresh')
@login_required
def api_discovery_refresh():
    cache.bust('discovery'); cache.bust('lxc_ips')
    return jsonify(run_discovery())

@app.route('/api/logs/<host_key>')
@login_required
def api_logs(host_key):
    # Primary source = the host's systemd journal via Proxmox pct exec. (Loki is the
    # intended central store but its promtail shippers are broken / it is empty, so we
    # read journals directly — reliable real-time logs on every CT.)
    cached = cache.get(f'logs:{host_key}', ttl=20)
    if cached is not None:
        return jsonify(cached)
    vmid = _host_vmid(host_key)
    if vmid and PROXMOX_PASS:
        try:
            raw = _prox_exec(vmid, 'journalctl -n 120 --no-pager -o short-iso 2>/dev/null', timeout=20)
            lines = [{'msg': l} for l in raw.splitlines() if l.strip()]
            if lines:
                res = {'host': host_key, 'source': 'journal', 'lines': lines[-120:]}
                cache.set(f'logs:{host_key}', res)
                return jsonify(res)
        except Exception:
            pass
    # fallback: Loki (legacy)
    h = STATIC_HOSTS.get(host_key)
    ip = h[1] if h else None
    lines = get_loki_logs(f'{{host=~"{ip}.*"}}', limit=40) if ip else []
    res = {'host': host_key, 'ip': ip, 'source': 'loki', 'lines': lines}
    cache.set(f'logs:{host_key}', res)
    return jsonify(res)

@app.route('/api/agent/<host_key>')
@login_required
def api_agent(host_key):
    h = STATIC_HOSTS.get(host_key)
    if not h:
        return jsonify({'error': 'Unknown host'}), 404
    ip = h[1]
    status  = get_agent_data(ip, timeout=3)
    docker  = get_agent_docker(ip, timeout=4)
    logs    = get_agent_logs(ip, timeout=4)
    return jsonify({'host': host_key, 'ip': ip, 'status': status,
                    'docker': docker, 'logs': logs})

@app.route('/api/agent/<host_key>/restart', methods=['POST'])
@login_required
def api_agent_restart(host_key):
    h = STATIC_HOSTS.get(host_key)
    if not h:
        return jsonify({'ok': False, 'error': 'Unknown host'}), 404
    ip   = h[1]
    name = request.json.get('name', '')
    try:
        req  = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/restart',
                                      data=json.dumps({'name': name}).encode(),
                                      method='POST')
        req.add_header('Authorization', f'Bearer {_agent_token(host_key)}')
        req.add_header('Content-Type', 'application/json')
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        cache.bust()
        return jsonify(resp)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/restart/<host_key>', methods=['POST'])
@login_required
def api_restart(host_key):
    RESTARTABLE = {}   # optional: host-key -> docker-Containername
    container = RESTARTABLE.get(host_key)
    if not container:
        return jsonify({'ok': False, 'error': 'Not in allowlist'}), 403
    try:
        r = subprocess.run(['docker', 'restart', container], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            cache.bust()
            return jsonify({'ok': True, 'message': f'Restarted {container}'})
        return jsonify({'ok': False, 'error': r.stderr.strip()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ─── AUDIT LOG ────────────────────────────────

@app.route('/api/container/<host_key>/<action>', methods=['POST'])
@admin_required
def api_container_action(host_key, action):
    name = (request.json or {}).get('name', '')
    _audit_user(f'container_{action}', host_key, name)
    return jsonify(container_action(host_key, name, action))

@app.route('/api/container/bulk', methods=['POST'])
@admin_required
def api_container_bulk():
    d = request.json or {}
    action = d.get('action', '')
    targets = d.get('targets', [])[:50]
    _audit_user(f'bulk_{action}', '', f'{len(targets)} targets')
    results = []
    for t in targets:
        r = container_action(t.get('host', ''), t.get('name', ''), action)
        results.append({'host': t.get('host'), 'name': t.get('name'), **r})
    ok_n = sum(1 for r in results if r.get('ok'))
    return jsonify({'ok': True, 'done': ok_n, 'total': len(results), 'results': results})

# ─── AI ANALYSIS (LiteLLM) ─────────────────────
def _llm_chat(messages, model=None, max_tokens=2000, temperature=0.3):
    model = model or LLM_MODEL or (_ll_read_models() or ['gpt-4o-mini'])[0]
    body = json.dumps({'model': model, 'messages': messages,
                       'max_tokens': max_tokens, 'temperature': temperature}).encode()
    req = urllib.request.Request(f'{LITELLM_URL}/v1/chat/completions', data=body, method='POST')
    req.add_header('Authorization', f'Bearer {LITELLM_KEY}')
    req.add_header('Content-Type', 'application/json')
    resp = json.loads(urllib.request.urlopen(req, timeout=90).read())
    return (resp.get('choices', [{}])[0].get('message', {}) or {}).get('content') or ''

def _build_ai_context(host_key=None):
    live = cache.get('live') or {}
    hosts = live.get('hosts', [])
    out = []
    s = live.get('summary', {})
    out.append(f"Cluster: {s.get('online', 0)} online, {s.get('degraded', 0)} degraded, "
               f"{s.get('offline', 0)} offline (gesamt {s.get('total', 0)}).")
    alerts = live.get('alerts', [])
    if alerts:
        out.append("Aktive Alarme:")
        for a in alerts[:15]:
            out.append(f"  - [{a.get('severity')}] {a.get('host')}: {a.get('msg')}")
    if host_key:
        h = next((x for x in hosts if x['key'] == host_key), None)
        if h:
            m = h.get('metrics') or {}; ag = h.get('agent') or {}
            out.append(f"\nHost {h.get('name')} (IP {h.get('ip')}, CT{h.get('ct_id')}): "
                       f"Status {h.get('status')}, CPU {m.get('cpu')}%, RAM {m.get('ram')}%, Disk {m.get('disk_pct')}%.")
            if ag:
                out.append(f"  OS {ag.get('os')}, Uptime {ag.get('uptime_h')}h, Load {ag.get('load')}, Agent {ag.get('agent_version')}.")
            down = [x.get('name') for x in (h.get('services') or []) if x.get('status') != 'online']
            if down:
                out.append(f"  Dienste nicht-online: {', '.join(down[:12])}")
            try:
                vmid = h.get('ct_id')
                logs = []
                if vmid and PROXMOX_PASS:
                    raw = _prox_exec(vmid, 'journalctl -n 40 --no-pager -o short-iso 2>/dev/null', timeout=15)
                    logs = [{'msg': l} for l in raw.splitlines() if l.strip()][-40:]
                if not logs:
                    logs = get_loki_logs(f'{{host=~"{h.get("ip")}.*"}}', limit=25)
                if logs:
                    out.append("  Letzte Logzeilen:")
                    for l in logs[-30:]:
                        out.append(f"    {str(l.get('msg', ''))[:160]}")
            except Exception:
                pass
    else:
        out.append("\nHosts:")
        for h in hosts[:30]:
            m = h.get('metrics') or {}
            out.append(f"  - {h.get('name')} [{h.get('status')}] CPU {m.get('cpu')}% RAM {m.get('ram')}%")
    return "\n".join(out)[:8000]

@app.route('/api/ai/analyze', methods=['POST'])
@login_required
def api_ai_analyze():
    d = request.json or {}
    question = (d.get('question') or '').strip()
    host_key = d.get('host_key') or None
    conv = d.get('conversation') or None
    execute = bool(d.get('execute'))
    if not question and not execute:
        return jsonify({'ok': False, 'error': 'Frage fehlt'})
    if ai_provider() == 'agy':
        if not agy_available():
            return jsonify({'ok': False, 'error': f'Antigravity (agy) nicht gefunden unter {AGY_BIN}'})
        user = session.get('username', '?')
        if execute:
            if session.get('role', 'admin') != 'admin':
                return jsonify({'ok': False, 'error': 'Nur Admins dürfen ausführen lassen'}), 403
            if not conv:
                return jsonify({'ok': False, 'error': 'Ausführen geht nur in einem bestehenden Gespräch'}), 400
            question = question or ('Freigegeben. Fuehre den vorgeschlagenen Plan jetzt aus. Berichte danach genau, '
                                    'was du geaendert hast und wie man es rueckgaengig macht.')
            prompt = question
        elif conv:
            prompt = question
        else:
            ctx = _build_ai_context(host_key)
            hn = (STATIC_HOSTS.get(host_key) or (host_key,))[0] if host_key else ''
            prompt = _AGY_FIRST_PROMPT.format(brand=BRAND, ctx=ctx[:6000], q=question,
                                              host=f' zu Host {hn}' if hn else '')
        if _agy_lock.locked():
            return jsonify({'ok': False, 'error': 'Antigravity arbeitet gerade an einer anderen Anfrage – bitte kurz warten'}), 409
        try:
            r = _agy_run(prompt, conv, execute=execute)
        except subprocess.TimeoutExpired:
            return jsonify({'ok': False, 'error': 'Zeitüberschreitung – Antigravity hat nicht rechtzeitig geantwortet'})
        conv = r.get('conversation_id') or conv
        mode = 'execute' if execute else 'plan'
        _ai_log(conv, 'user', mode, question, user, host_key)
        _ai_log(conv, 'assistant', mode, r.get('answer') or f"Fehler: {r.get('error')}", user, host_key)
        _audit_user('ai_execute' if execute else 'ai_analyze', host_key or '', question[:80])
        return jsonify({'ok': r['ok'], 'answer': r.get('answer'), 'error': r.get('error'), 'model': 'Antigravity',
                        'conversation_id': conv, 'mode': mode, 'host_key': host_key})
    if not LITELLM_KEY:
        return jsonify({'ok': False, 'error': 'LITELLM_KEY nicht gesetzt'})
    ctx = _build_ai_context(host_key)
    messages = [
        {'role': 'system', 'content':
            'Du bist der KI-Analyst der überwachten Infrastruktur (Proxmox, LXC, Docker, '
            'Prometheus, Loki, UniFi). Antworte auf Deutsch, knapp und konkret. Stütze dich nur '
            'auf die gegebenen Daten; wenn etwas fehlt, sage es. Gib bei Problemen mögliche '
            'Ursachen und konkrete nächste Schritte.'},
        {'role': 'user', 'content': f'INFRASTRUKTUR-KONTEXT:\n{ctx}\n\nFRAGE: {question}'},
    ]
    _audit_user('ai_analyze', host_key or '', question[:80])
    try:
        answer = _llm_chat(messages) or '(keine Antwort vom Modell — evtl. Token-Limit)'
        return jsonify({'ok': True, 'answer': answer, 'model': LLM_MODEL or 'LiteLLM', 'host_key': host_key})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/lxc/<host_key>/<action>', methods=['POST'])
@admin_required
def api_lxc_action(host_key, action):
    _audit_user(f'lxc_{action}', host_key, '')
    return jsonify(lxc_action(host_key, action))

_acked_alerts = {}  # signature -> ts

def _alert_sig(a):
    return f"{a.get('key')}|{a.get('msg')}"

@app.route('/api/alerts')
@login_required
def api_alerts():
    cached = cache.get('live', ttl=CACHE_TTL)
    alerts = cached.get('alerts', []) if cached else []
    for a in alerts:
        a['acked'] = _alert_sig(a) in _acked_alerts
    return jsonify(alerts)

@app.route('/api/alerts/ack', methods=['POST'])
@login_required
def api_alerts_ack():
    d = request.json or {}
    sig = d.get('sig')
    if sig:
        _acked_alerts[sig] = time.time()
        # prune old acks (>24h) so cleared-then-recurring alerts re-appear
        cutoff = time.time() - 86400
        for k in [k for k, v in _acked_alerts.items() if v < cutoff]:
            _acked_alerts.pop(k, None)
    return jsonify({'ok': True})

# ─── SERVICE BOARD (Homarr-style launcher) ─────
def _board_ensure():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('CREATE TABLE IF NOT EXISTS board (id INTEGER PRIMARY KEY CHECK (id=1), tiles_json TEXT)')
    conn.commit(); conn.close()

def _board_seed():
    """Auto-build tiles from discovered services that have a URL."""
    live = cache.get('live') or {}
    tiles, seen = [], set()
    for h in live.get('hosts', []):
        for s in (h.get('services') or []):
            url = s.get('url')
            if url and url not in seen:
                seen.add(url)
                tiles.append({'name': s.get('name'), 'url': url,
                              'icon': h.get('icon') or '🔗', 'cat': h.get('category') or 'service'})
    return tiles

@app.route('/api/board', methods=['GET'])
@login_required
def api_board_get():
    _board_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute('SELECT tiles_json FROM board WHERE id=1').fetchone()
    conn.close()
    if row and row[0]:
        try:
            return jsonify(json.loads(row[0]))
        except Exception:
            pass
    return jsonify(_board_seed())

@app.route('/api/board/discovered', methods=['GET'])
@login_required
def api_board_discovered():
    return jsonify(_board_seed())

@app.route('/api/board', methods=['PUT'])
@admin_required
def api_board_put():
    _board_ensure()
    body = request.json
    tiles = body if isinstance(body, list) else (body or {}).get('tiles', [])
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('INSERT INTO board (id,tiles_json) VALUES (1,?) '
                 'ON CONFLICT(id) DO UPDATE SET tiles_json=excluded.tiles_json',
                 (json.dumps(tiles),))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'count': len(tiles)})

# ─── AUTOMATIONS (event rules: when X then Y) ──
def _auto_ensure():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS automations (
        id TEXT PRIMARY KEY, name TEXT, scope_host TEXT, metric TEXT, op TEXT,
        threshold TEXT, action TEXT, action_arg TEXT, enabled INTEGER DEFAULT 1,
        cooldown_min INTEGER DEFAULT 30, last_fired INTEGER DEFAULT 0, created_at TEXT)''')
    conn.commit(); conn.close()

def _auto_list():
    _auto_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute('SELECT * FROM automations ORDER BY created_at DESC').fetchall()]
    conn.close()
    return rows

def _auto_cond_met(rule, h):
    m = h.get('metrics') or {}
    metric = rule['metric']
    if metric == 'status':
        return h.get('status') == rule['threshold']
    val = {'cpu': m.get('cpu'), 'ram': m.get('ram'), 'disk': m.get('disk_pct')}.get(metric)
    if val is None:
        return False
    try:
        thr = float(rule['threshold'])
    except Exception:
        return False
    op = rule['op']
    return (op == '>' and val > thr) or (op == '<' and val < thr) or (op == '==' and val == thr)

def _auto_run_action(rule, h):
    action, arg = rule['action'], rule.get('action_arg') or ''
    hk, name = h['key'], h['name']
    if action == 'telegram':
        _tg_send(f"🤖 *Automation:* {rule['name']}\n*Host:* {name}\n{arg or 'Bedingung erfüllt'}")
        return 'Telegram gesendet'
    if action == 'lxc_reboot':
        r = lxc_action(hk, 'reboot')
        _tg_send(f"🤖 Automation {rule['name']}: CT {name} Reboot → {r.get('msg', r)}")
        return f"Reboot: {r.get('msg', r.get('error'))}"
    if action == 'restart_container':
        r = container_action(hk, arg, 'restart')
        _tg_send(f"🤖 Automation {rule['name']}: Container {arg}@{name} Neustart → {r.get('msg', r)}")
        return f"Restart {arg}: {r.get('msg', r.get('error'))}"
    if action == 'ai_diagnose':
        try:
            ans = _llm_chat([
                {'role': 'system', 'content': 'Du bist Infra-Analyst. Antworte sehr knapp auf Deutsch: wahrscheinliche Ursache + 1 Empfehlung.'},
                {'role': 'user', 'content': f'KONTEXT:\n{_build_ai_context(hk)}\n\nWarum ist die Bedingung "{rule["metric"]} {rule["op"]} {rule["threshold"]}" auf {name} erfüllt?'}],
                max_tokens=1500)
            _tg_send(f"🤖 *KI-Diagnose* {name} ({rule['name']}):\n{ans[:1000]}")
            return f"KI: {ans[:160]}"
        except Exception as e:
            return f"KI-Fehler: {e}"
    return 'unbekannte Aktion'

def _automations_tick():
    live = cache.get('live')
    if not live:
        return
    rules = [r for r in _auto_list() if r.get('enabled')]
    if not rules:
        return
    now = int(time.time())
    hosts = live.get('hosts', [])
    for r in rules:
        if now - (r.get('last_fired') or 0) < (r.get('cooldown_min', 30) * 60):
            continue
        targets = [h for h in hosts if (not r['scope_host'] or h['key'] == r['scope_host'])]
        fired_host = None
        for h in targets:
            if _auto_cond_met(r, h):
                fired_host = h
                break
        if fired_host:
            try:
                result = _auto_run_action(r, fired_host)
            except Exception as e:
                result = f'Fehler: {e}'
            conn = sqlite3.connect(AUDIT_DB)
            conn.execute('UPDATE automations SET last_fired=? WHERE id=?', (now, r['id']))
            conn.commit(); conn.close()
            _nc_log(fired_host['key'], 'automation',
                    f"{r['name']}: {r['metric']} {r['op']} {r['threshold']}", result, 'warn')

def _automations_bg():
    while True:
        try:
            _automations_tick()
        except Exception as e:
            print(f'[automations] {e}')
        time.sleep(60)

@app.route('/api/automations', methods=['GET'])
@login_required
def api_auto_list():
    return jsonify(_auto_list())

@app.route('/api/automations', methods=['POST'])
@admin_required
def api_auto_create():
    import secrets as _s
    d = request.json or {}
    if not d.get('name') or not d.get('action'):
        return jsonify({'ok': False, 'error': 'name + action erforderlich'}), 400
    _auto_ensure()
    rid = _s.token_hex(5)
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''INSERT INTO automations
        (id,name,scope_host,metric,op,threshold,action,action_arg,enabled,cooldown_min,last_fired,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,0,?)''',
        (rid, d['name'], d.get('scope_host', ''), d.get('metric', 'cpu'), d.get('op', '>'),
         str(d.get('threshold', '90')), d['action'], d.get('action_arg', ''),
         1 if d.get('enabled', True) else 0, int(d.get('cooldown_min', 30)),
         time.strftime('%Y-%m-%dT%H:%M:%S')))
    conn.commit(); conn.close()
    _audit_user('auto_create', '', d['name'])
    return jsonify({'ok': True, 'id': rid})

@app.route('/api/automations/<rid>', methods=['PATCH'])
@admin_required
def api_auto_patch(rid):
    d = request.json or {}
    _auto_ensure()
    fields = [k for k in ('name', 'scope_host', 'metric', 'op', 'threshold', 'action', 'action_arg', 'enabled', 'cooldown_min') if k in d]
    if not fields:
        return jsonify({'ok': True})
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute(f"UPDATE automations SET {', '.join(f'{f}=?' for f in fields)} WHERE id=?",
                 [(1 if d[f] else 0) if f == 'enabled' else d[f] for f in fields] + [rid])
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/automations/<rid>', methods=['DELETE'])
@admin_required
def api_auto_delete(rid):
    _auto_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('DELETE FROM automations WHERE id=?', (rid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/automations/<rid>/test', methods=['POST'])
@admin_required
def api_auto_test(rid):
    rule = next((r for r in _auto_list() if r['id'] == rid), None)
    if not rule:
        return jsonify({'ok': False, 'error': 'nicht gefunden'}), 404
    live = cache.get('live') or {}
    hosts = live.get('hosts', [])
    h = next((x for x in hosts if (not rule['scope_host'] or x['key'] == rule['scope_host'])), hosts[0] if hosts else None)
    if not h:
        return jsonify({'ok': False, 'error': 'kein Host'})
    result = _auto_run_action(rule, h)
    return jsonify({'ok': True, 'result': result, 'host': h['name']})

@app.route('/api/processes/<host_key>')
@login_required
def api_processes(host_key):
    h = STATIC_HOSTS.get(host_key)
    if not h:
        return jsonify({'error': 'Unknown host'}), 404
    ip = h[1]
    try:
        req = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/procs')
        req.add_header('Authorization', f'Bearer {_agent_token(host_key)}')
        resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
        return jsonify(resp)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/me')
@login_required
def api_me():
    um = _user_mfa(session.get('username')) or {}
    return jsonify({'username': session.get('username'), 'role': session.get('role', 'admin'),
                    'mfa': um.get('enabled', False), 'brand': BRAND})

@app.route('/api/me/password', methods=['POST'])
@login_required
def api_me_password():
    d = request.json or {}
    old, new = d.get('old', ''), d.get('new', '')
    u = session.get('username')
    dbu = _user_get(u)
    ok = (dbu and check_password_hash(dbu['pw_hash'], old)) or (u in USERS and check_password_hash(USERS[u], old))
    if not ok:
        return jsonify({'ok': False, 'error': 'Aktuelles Passwort falsch'}), 400
    if len(new) < 4:
        return jsonify({'ok': False, 'error': 'Neues Passwort zu kurz (min. 4)'}), 400
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('INSERT INTO users (username,pw_hash,role,created_at) VALUES (?,?,?,?) '
                 'ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash',
                 (u, generate_password_hash(new), (dbu or {}).get('role', 'admin'), time.strftime('%Y-%m-%dT%H:%M:%S')))
    conn.commit(); conn.close()
    _audit_user('password_change', u, '')
    return jsonify({'ok': True})

@app.route('/api/grafana/dashboards')
@login_required
def api_grafana_dashboards():
    try:
        r = urllib.request.urlopen(f'{GRAFANA_URL}/api/search?type=dash-db', timeout=5)
        data = json.loads(r.read())
        dbs = [{'uid': d.get('uid'), 'title': d.get('title'), 'url': d.get('url')} for d in data]
        return jsonify({'base': GRAFANA_URL, 'dashboards': dbs})
    except Exception as e:
        return jsonify({'base': GRAFANA_URL, 'dashboards': [], 'error': str(e)})

@app.route('/api/integrations')
@login_required
def api_integrations():
    out = []
    def add(name, state, detail='', how=''):
        # state: True = ok, False = Fehler, None = nicht eingerichtet
        out.append({'name': name, 'ok': state is True,
                    'state': 'ok' if state is True else ('off' if state is None else 'error'),
                    'detail': str(detail)[:160], 'how': how})
    def check(name, configured, how, fn):
        if not configured:
            return add(name, None, 'nicht eingerichtet', how)
        try:
            ok, detail = fn()
            add(name, ok, detail, how)
        except Exception as e:
            add(name, False, e, how)
    def _pve():
        nd = _px(f'/nodes/{PROXMOX_NODE}/status')
        return bool(nd and 'data' in nd), (f'API erreichbar · Node {PROXMOX_NODE}' if nd else 'kein Zugriff (Token/Rechte prüfen)')
    check('Proxmox', bool(PROXMOX_HOST and (PROXMOX_TOKEN or PROXMOX_PASS)), 'PROXMOX_HOST + PROXMOX_TOKEN', _pve)
    def _prom():
        prom = get_prometheus(); return bool(prom), f'{len(prom)} Hosts mit Metriken'
    check('Prometheus', bool(PROMETHEUS), 'PROMETHEUS_URL', _prom)
    def _loki():
        ready = 'ready' in urllib.request.urlopen(f'{LOKI_URL}/ready', timeout=4).read().decode().lower()
        return ready, 'bereit' if ready else 'nicht bereit'
    check('Loki', bool(LOKI_URL), 'LOKI_URL', _loki)
    def _unifi():
        u = get_unifi_data(); return bool(u), (f"{len((u or {}).get('clients', []))} Clients" if u else 'Login fehlgeschlagen')
    check('UniFi', bool(UNIFI_URL and UNIFI_USER), 'UNIFI_URL + UNIFI_USER + UNIFI_PASS', _unifi)
    def _llm():
        ll = get_litellm_status()
        if not (ll and ll.get('alive')):
            return False, 'nicht erreichbar'
        if not LITELLM_KEY:
            return False, 'erreichbar, aber LITELLM_KEY fehlt'
        ans = _llm_chat([{'role': 'user', 'content': 'sage ok'}], max_tokens=50)
        return bool(ans), 'antwortet' if ans else 'keine Antwort'
    check('KI (LiteLLM / OpenAI-kompatibel)', bool(LITELLM_URL), 'LITELLM_URL + LITELLM_KEY', _llm)
    check('Dokploy', bool(DOKPLOY_URL), 'DOKPLOY_URL + DOKPLOY_API_KEY',
          lambda: (bool(DOKPLOY_KEY), 'Token gesetzt' if DOKPLOY_KEY else 'DOKPLOY_API_KEY fehlt'))
    check('Coolify', bool(COOLIFY_URL), 'COOLIFY_URL + COOLIFY_API_KEY',
          lambda: (bool(COOLIFY_KEY), 'Token gesetzt' if COOLIFY_KEY else 'COOLIFY_API_KEY fehlt'))
    check('Telegram-Alarme', bool(TELEGRAM_TOKEN), 'TELEGRAM_TOKEN + TELEGRAM_CHAT_ID',
          lambda: (bool(TELEGRAM_CHAT_ID), 'bereit' if TELEGRAM_CHAT_ID else 'TELEGRAM_CHAT_ID fehlt'))
    agents = _agents_list()
    online = sum(1 for a in agents if not a['stale'])
    add('Agenten', True if online else None,
        f'{online} von {len(agents)} melden sich' if agents else 'noch keine installiert',
        'unter „Hosts & Agenten" installieren')
    return jsonify(out)

@app.route('/api/mfa/setup', methods=['POST'])
@login_required
def api_mfa_setup():
    import pyotp, io, qrcode, qrcode.image.svg
    u = session.get('username')
    secret = pyotp.random_base32()
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('UPDATE users SET mfa_secret=?, mfa_enabled=0 WHERE username=?', (secret, u))
    conn.commit(); conn.close()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=u, issuer_name=BRAND)
    buf = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage).save(buf)
    return jsonify({'secret': secret, 'uri': uri, 'qr_svg': buf.getvalue().decode()})

@app.route('/api/mfa/enable', methods=['POST'])
@login_required
def api_mfa_enable():
    import pyotp
    u = session.get('username')
    code = (request.json or {}).get('code', '').strip()
    um = _user_mfa(u)
    if not (um and um['secret'] and pyotp.TOTP(um['secret']).verify(code, valid_window=1)):
        return jsonify({'ok': False, 'error': 'Code ungültig'}), 400
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('UPDATE users SET mfa_enabled=1 WHERE username=?', (u,))
    conn.commit(); conn.close()
    _audit_user('mfa_enable', u, '')
    return jsonify({'ok': True})

@app.route('/api/mfa/disable', methods=['POST'])
@login_required
def api_mfa_disable():
    import pyotp
    u = session.get('username')
    code = (request.json or {}).get('code', '').strip()
    um = _user_mfa(u)
    if um and um['enabled']:
        if not (um['secret'] and pyotp.TOTP(um['secret']).verify(code, valid_window=1)):
            return jsonify({'ok': False, 'error': 'Code ungültig'}), 400
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('UPDATE users SET mfa_enabled=0, mfa_secret=NULL WHERE username=?', (u,))
    conn.commit(); conn.close()
    _audit_user('mfa_disable', u, '')
    return jsonify({'ok': True})

@app.route('/api/users', methods=['GET'])
@admin_required
def api_users_list():
    _users_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    rows = conn.execute('SELECT username,role,created_at,last_login FROM users ORDER BY username').fetchall()
    conn.close()
    return jsonify([{'username': r[0], 'role': r[1], 'created_at': r[2], 'last_login': r[3]} for r in rows])

@app.route('/api/users', methods=['POST'])
@admin_required
def api_users_create():
    d = request.json or {}
    u = (d.get('username') or '').strip().lower()
    p = d.get('password') or ''
    role = d.get('role', 'viewer')
    if not u or not p:
        return jsonify({'ok': False, 'error': 'username + password erforderlich'}), 400
    if role not in ('admin', 'viewer'):
        role = 'viewer'
    _users_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('INSERT INTO users (username,pw_hash,role,created_at) VALUES (?,?,?,?) '
                 'ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash, role=excluded.role',
                 (u, generate_password_hash(p), role, time.strftime('%Y-%m-%dT%H:%M:%S')))
    conn.commit(); conn.close()
    _audit_user('user_create', u, role)
    return jsonify({'ok': True})

@app.route('/api/users/<username>', methods=['DELETE'])
@admin_required
def api_users_delete(username):
    username = username.strip().lower()
    if username == session.get('username'):
        return jsonify({'ok': False, 'error': 'Eigenen Account nicht löschen'}), 400
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('DELETE FROM users WHERE username=?', (username,))
    conn.commit(); conn.close()
    _audit_user('user_delete', username, '')
    return jsonify({'ok': True})

@app.route('/api/settings')
@login_required
def api_settings():
    hermes = [
        {'name': name, 'token_hint': tok[:6] + '…' + tok[-3:]}
        for tok, name in HERMES_AGENTS.items()
    ]
    agent_hosts = [
        {'key': k, 'name': h[0], 'ip': h[1], 'ct_id': h[4]}
        for k, h in STATIC_HOSTS.items()
        if h[4] or k.startswith('agent-')
    ]
    return jsonify({
        'agent_token':          GL_AGENT_TOKEN,
        'agent_port':           AGENT_PORT,
        'hermes_agents':        hermes,
        'agent_hosts':          agent_hosts,
        'dashboard_url':        os.environ.get('DASHBOARD_URL', ''),
        'telegram_configured':  bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
        'telegram_chat_id':     TELEGRAM_CHAT_ID[:6] + '…' if TELEGRAM_CHAT_ID else '',
        'version':              APP_VERSION,
        'public_status':        PUBLIC_STATUS,
    })

@app.route('/api/alert-thresholds', methods=['GET'])
@login_required
def api_thresholds_get():
    return jsonify(_get_thresholds())

@app.route('/api/alert-thresholds', methods=['POST'])
@admin_required
def api_thresholds_set():
    d = request.json or {}
    thr = dict(DEFAULT_THRESHOLDS)
    for k, (lo, hi) in {'cpu_warn': (1, 100), 'ram_warn': (1, 100),
                        'disk_crit': (1, 100), 'ssl_warn_days': (1, 365)}.items():
        if k in d:
            try:
                v = float(d[k])
            except (TypeError, ValueError):
                return jsonify({'ok': False, 'error': f'{k}: keine Zahl'}), 400
            if not lo <= v <= hi:
                return jsonify({'ok': False, 'error': f'{k}: muss zwischen {lo} und {hi} liegen'}), 400
            thr[k] = v
    _setting_set('alert_thresholds', json.dumps(thr))
    cache.bust('thresholds')
    _audit_user('thresholds_update', '', json.dumps(thr))
    return jsonify({'ok': True, 'thresholds': thr})

@app.route('/api/audit')
@login_required
def api_audit():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute(
            'SELECT ts,user,action,host_key,detail FROM audit ORDER BY ts DESC LIMIT 200'
        ).fetchall()
        conn.close()
        return jsonify([{'ts': r[0], 'user': r[1], 'action': r[2], 'host': r[3], 'detail': r[4]} for r in rows])
    except Exception:
        return jsonify([])

@app.route('/api/inventory')
@login_required
def api_inventory():
    return jsonify(_inv_all_summary())

@app.route('/api/inventory/search')
@login_required
def api_inventory_search():
    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify([])
    _inv_ensure_table()
    conn = sqlite3.connect(AUDIT_DB)
    rows = conn.execute('SELECT host_key,os,packages_json FROM inventory').fetchall()
    conn.close()
    results = []
    for host_key, os_name, pj in rows:
        try:
            pkgs = json.loads(pj or '{}')
        except Exception:
            pkgs = {}
        for name, ver in pkgs.items():
            if q in name.lower():
                results.append({'host_key': host_key, 'os': os_name, 'package': name, 'version': ver})
    results.sort(key=lambda x: (x['package'], x['host_key']))
    return jsonify(results[:500])

@app.route('/api/inventory/<host_key>')
@login_required
def api_inventory_host(host_key):
    _inv_ensure_table()
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute('SELECT host_key,vmid,os,version_id,python,kernel,pkg_count,packages_json,scanned_at '
                       'FROM inventory WHERE host_key=?', (host_key,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'host_key': host_key, 'scanned': False, 'packages': {}})
    try:
        pkgs = json.loads(row[7] or '{}')
    except Exception:
        pkgs = {}
    return jsonify({'host_key': row[0], 'vmid': row[1], 'os': row[2], 'version_id': row[3],
                    'python': row[4], 'kernel': row[5], 'pkg_count': row[6],
                    'packages': pkgs, 'scanned_at': row[8], 'scanned': True})

@app.route('/api/inventory/<host_key>/scan', methods=['POST'])
@login_required
def api_inventory_scan(host_key):
    _audit_user('inv_scan', host_key, '')
    return jsonify(scan_host_inventory(host_key))

@app.route('/api/inventory/scan-all', methods=['POST'])
@login_required
def api_inventory_scan_all():
    # Iterate STATIC_HOSTS directly (every LXC has a ct_id) — independent of the
    # live cache, which may be empty/stale inside a background thread.
    keys = [k for k, h in STATIC_HOSTS.items() if h[4]]
    def _bg():
        for key in keys:
            try:
                scan_host_inventory(key)
            except Exception:
                pass
    threading.Thread(target=_bg, daemon=True).start()
    _audit_user('inv_scan_all', '', f'{len(keys)} hosts')
    return jsonify({'ok': True, 'msg': f'Scan von {len(keys)} LXC gestartet (Hintergrund)'})

@app.route('/api/nanoclaw/events')
@login_required
def api_nc_events():
    # Collect events from all agent hosts in parallel
    live = cache.get('live')
    all_events = list(reversed(_nc_events[-50:]))  # dashboard-side events first

    if live:
        agent_hosts = [(h['key'], h['ip']) for h in live.get('hosts', [])
                       if h.get('ct_id') and h.get('status') == 'online']
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = {pool.submit(get_agent_nc_events, ip): key
                       for key, ip in agent_hosts}
            for f in as_completed(futures, timeout=5):
                try:
                    result = f.result()
                    if result and result.get('events'):
                        all_events.extend(result['events'])
                except Exception:
                    pass

    # Sort by ts descending
    all_events.sort(key=lambda e: e.get('ts', 0), reverse=True)
    return jsonify(all_events[:200])

@app.route('/api/nanoclaw/diagnose/<host_key>/<path:container_name>')
@login_required
def api_nc_diagnose(host_key, container_name):
    h = STATIC_HOSTS.get(host_key)
    if not h:
        live = cache.get('live')
        if live:
            hobj = next((x for x in live.get('hosts', []) if x['key'] == host_key), None)
            ip = hobj['ip'] if hobj else None
        else:
            ip = None
    else:
        ip = h[1]
    if not ip:
        return jsonify({'ok': False, 'advice': 'Host nicht gefunden'}), 404
    source = request.args.get('source', 'docker')
    _audit_user('nc_diagnose', host_key, f'{source}:{container_name}')
    return jsonify(nc_diagnose(ip, container_name, source=source))

@app.route('/api/nanoclaw/status')
@login_required
def api_nc_status():
    return jsonify({
        'events_total': len(_nc_events),
        'hosts_tracked': len(_nc_state),
        'recent': list(reversed(_nc_events[-5:])),
        'cooldowns': {k: round(time.time() - v) for k, v in _nc_cooldowns.items()},
    })

@app.route('/api/unifi')
@login_required
def api_unifi():
    return jsonify(get_unifi_data() or {})

# ─── LITELLM ──────────────────────────────────
_ll_models_cache = {'models': [], 'ts': 0}
LLM_MODEL = os.environ.get('LLM_MODEL', '')
_LL_FALLBACK_MODELS = [LLM_MODEL] if LLM_MODEL else []

def _ll_read_models():
    now = time.time()
    if now - _ll_models_cache['ts'] < 3600 and _ll_models_cache['models']:
        return _ll_models_cache['models']
    try:
        req = urllib.request.Request(f'{LITELLM_URL}/v1/models')
        if LITELLM_KEY:
            req.add_header('Authorization', f'Bearer {LITELLM_KEY}')
        models = [m['id'] for m in json.loads(urllib.request.urlopen(req, timeout=6).read()).get('data', [])]
        if models:
            _ll_models_cache['models'] = models
            _ll_models_cache['ts'] = now
        return models or _LL_FALLBACK_MODELS
    except Exception as e:
        print(f'[LiteLLM] models: {e}')
        return _ll_models_cache['models'] or _LL_FALLBACK_MODELS

def get_litellm_status():
    cached = cache.get('litellm', ttl=30)
    if cached is not None:
        return cached
    result = {'alive': False, 'ready': False, 'db': False, 'models': _LL_FALLBACK_MODELS, 'model_count': 0}
    try:
        req = urllib.request.Request(f'{LITELLM_URL}/health/liveliness')
        if LITELLM_KEY:
            req.add_header('Authorization', f'Bearer {LITELLM_KEY}')
        resp = urllib.request.urlopen(req, timeout=5)
        result['alive'] = 'alive' in resp.read().decode().lower()
    except Exception:
        pass
    try:
        req2 = urllib.request.Request(f'{LITELLM_URL}/health/readiness')
        resp2 = urllib.request.urlopen(req2, timeout=5)
        r2 = json.loads(resp2.read())
        result['ready'] = r2.get('status') == 'healthy'
        result['db']    = 'Not connected' not in r2.get('db', 'Not connected')
    except Exception:
        pass
    models = _ll_read_models()
    result['models'] = models
    result['model_count'] = len(models)
    cache.set('litellm', result)
    return result

@app.route('/api/host_meta', methods=['GET'])
@login_required
def api_host_meta_get():
    return jsonify(_get_host_meta())

@app.route('/api/host_meta/<host_key>', methods=['PATCH'])
@admin_required
def api_host_meta_patch(host_key):
    d = request.json or {}
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''INSERT INTO host_meta (host_key,category,display_name,notes,updated_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(host_key) DO UPDATE SET
                        category=excluded.category,
                        display_name=excluded.display_name,
                        notes=excluded.notes,
                        updated_at=excluded.updated_at''',
                 (host_key, d.get('category'), d.get('display_name'), d.get('notes',''), now))
    conn.commit(); conn.close()
    _audit_user('host_meta', host_key, f"cat={d.get('category')}")
    cache.bust('live')
    return jsonify({'ok': True})

@app.route('/api/tokens', methods=['GET'])
@login_required
def api_tokens_list():
    try:
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute('SELECT id,name,token,created_at,last_seen FROM agent_tokens ORDER BY created_at DESC').fetchall()
        conn.close()
        return jsonify([{'id': r[0], 'name': r[1], 'token': r[2], 'created_at': r[3], 'last_seen': r[4]} for r in rows])
    except Exception:
        return jsonify([])

@app.route('/api/tokens', methods=['POST'])
@admin_required
def api_tokens_create():
    import secrets as _sec
    d = request.json or {}
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Name required'}), 400
    token = 'gl-' + _sec.token_hex(16)
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    tid = str(_uuid.uuid4())
    try:
        conn = sqlite3.connect(AUDIT_DB)
        conn.execute('INSERT INTO agent_tokens (id,name,token,created_at) VALUES (?,?,?,?)',
                     (tid, name, token, now))
        conn.commit(); conn.close()
        _audit_user('token_create', name, token[:12]+'…')
        return jsonify({'ok': True, 'id': tid, 'name': name, 'token': token})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/tokens/<token_id>', methods=['DELETE'])
@admin_required
def api_tokens_delete(token_id):
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('DELETE FROM agent_tokens WHERE id=?', (token_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/litellm')
@login_required
def api_litellm():
    return jsonify(get_litellm_status() or {})

# ─── DOKPLOY ──────────────────────────────────
_DOKPLOY_INFRA_SKIP = {'dokploy', 'dokploy-postgres', 'dokploy-redis', 'portainer',
                        'promtail', 'node-exporter'}

def get_dokploy_apps():
    cached = cache.get('dokploy_apps', ttl=30)
    if cached is not None:
        return cached

    if not DOKPLOY_URL:
        return {}
    docker_data = get_agent_docker(urllib.parse.urlparse(DOKPLOY_URL).hostname or '')
    apps = []
    if docker_data and docker_data.get('containers'):
        for c in docker_data['containers']:
            if c.get('source') == 'systemd':
                continue
            name = c.get('name', '')
            name_lower = name.lower()
            if any(skip in name_lower for skip in _DOKPLOY_INFRA_SKIP):
                continue
            st = c.get('status', '')
            is_up = st.lower().startswith('up') or 'running' in st.lower()
            display = re.sub(r'\.\d+\.[a-z0-9]+$', '', name)
            apps.append({
                'name':       display,
                'image':      c.get('image', ''),
                'status':     'online' if is_up else 'offline',
                'status_raw': st,
                'ports':      c.get('ports', ''),
            })

    if DOKPLOY_KEY:
        try:
            url = f'{DOKPLOY_URL}/api/trpc/project.all?batch=1&input=%7B%220%22%3A%7B%22json%22%3Anull%7D%7D'
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {DOKPLOY_KEY}')
            resp = urllib.request.urlopen(req, timeout=5)
            dk = json.loads(resp.read())
            if isinstance(dk, list) and dk:
                projects = dk[0].get('result', {}).get('data', {}).get('json', []) or []
                proj_map = {p.get('name', '').lower(): p for p in projects}
                for a in apps:
                    for pname, pd in proj_map.items():
                        if pname in a['name'].lower():
                            a['project'] = pd.get('name')
                            break
        except Exception as e:
            print(f'[Dokploy] API: {e}')

    result = {
        'apps':        apps,
        'apps_total':  len(apps),
        'apps_online': sum(1 for a in apps if a['status'] == 'online'),
        'has_api':     bool(DOKPLOY_KEY),
    }
    cache.set('dokploy_apps', result)
    return result

@app.route('/api/dokploy')
@login_required
def api_dokploy():
    return jsonify(get_dokploy_apps() or {})

# ─── NEW v12 ENDPOINTS ────────────────────────────────────────────────────

@app.route('/api/ssl')
@login_required
def api_ssl():
    return jsonify(get_ssl_all())

@app.route('/api/backups')
@login_required
def api_backups():
    return jsonify(get_backup_jobs() or {})

@app.route('/api/loki/search')
@login_required
def api_loki_search():
    q     = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', '200')), 500)
    if not q: return jsonify([])
    safe  = q.replace('"', '\\"').replace('`', '\\`')
    lines = get_loki_logs(f'{{job=~".+"}} |= "{safe}"', limit=limit)
    return jsonify(lines)

@app.route('/api/telegram/test', methods=['POST'])
@login_required
def api_telegram_test():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return jsonify({'ok': False, 'configured': False,
                        'error': 'TELEGRAM_TOKEN + TELEGRAM_CHAT_ID env vars nicht gesetzt'})
    ok = _tg_send(f'🟢 *{BRAND}*\nTest-Nachricht — alles funktioniert! ✅')
    return jsonify({'ok': ok, 'configured': True})

@app.route('/api/metrics/<host_key>/history')
@login_required
def api_metrics_history(host_key):
    hours  = min(int(request.args.get('hours', '24')), 168)
    metric = request.args.get('metric', 'cpu')
    if metric not in ('cpu', 'ram', 'disk'): metric = 'cpu'
    cutoff = int(time.time()) - hours * 3600
    try:
        conn = sqlite3.connect(AUDIT_DB)
        rows = conn.execute(f'SELECT ts,{metric} FROM metrics_history WHERE host_key=? AND ts>? AND {metric} IS NOT NULL ORDER BY ts',
                           (host_key, cutoff)).fetchall()
        conn.close()
        # Downsample if too many points (keep max 200)
        if len(rows) > 200:
            step = len(rows) // 200
            rows = rows[::step]
        return jsonify([{'ts': r[0], 'v': round(r[1], 1)} for r in rows])
    except Exception:
        return jsonify([])

@app.route('/api/dependencies')
@login_required
def api_dependencies():
    reverse = {}
    for key, deps in DEPENDENCIES.items():
        for dep in deps:
            reverse.setdefault(dep, []).append(key)
    return jsonify({'deps': DEPENDENCIES, 'used_by': reverse})

# ─── HERMES AGENT API ─────────────────────────

def _hermes_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key  = request.headers.get('X-Hermes-Key', '') or request.args.get('key', '')
        name = HERMES_AGENTS.get(key)
        if not name:
            return jsonify({'error': 'Unauthorized'}), 401
        request.hermes_agent = name
        return f(*args, **kwargs)
    return decorated

@app.route('/api/v1/hosts')
@_hermes_auth
def v1_hosts():
    data = run_live_checks()
    _audit(request.hermes_agent, 'api_hosts', '*')
    return jsonify({'hosts': [
        {k: h[k] for k in ('key','name','ip','status','category','metrics','agent')}
        for h in data['hosts']
    ]})

@app.route('/api/v1/host/<host_key>')
@_hermes_auth
def v1_host(host_key):
    data  = run_live_checks()
    host  = next((h for h in data['hosts'] if h['key'] == host_key), None)
    if not host: return jsonify({'error': 'Not found'}), 404
    _audit(request.hermes_agent, 'api_host', host_key)
    return jsonify(host)

@app.route('/api/v1/host/<host_key>/agent')
@_hermes_auth
def v1_host_agent(host_key):
    h = STATIC_HOSTS.get(host_key)
    if not h: return jsonify({'error': 'Not found'}), 404
    ip = h[1]
    _audit(request.hermes_agent, 'api_agent', host_key, ip)
    return jsonify({
        'status':     get_agent_data(ip, timeout=3),
        'docker':     get_agent_docker(ip, timeout=4),
        'logs':       get_agent_logs(ip, timeout=4),
    })

@app.route('/api/v1/host/<host_key>/restart', methods=['POST'])
@_hermes_auth
def v1_host_restart(host_key):
    h = STATIC_HOSTS.get(host_key)
    if not h: return jsonify({'error': 'Not found'}), 404
    ip   = h[1]
    name = (request.json or {}).get('name', '')
    _audit(request.hermes_agent, 'restart', host_key, f'container={name}')
    try:
        req  = urllib.request.Request(f'http://{ip}:{AGENT_PORT}/restart',
                                      data=json.dumps({'name': name}).encode(), method='POST')
        req.add_header('Authorization', f'Bearer {_agent_token(host_key)}')
        req.add_header('Content-Type', 'application/json')
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return jsonify(resp)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ─── SSH TERMINAL (WebSocket) ──────────────────

@socketio.on('ssh_open')
def ws_ssh_open(data):
    if not session.get('authenticated'):
        emit('ssh_data', {'d': '\r\n[GL] Unauthorized\r\n'}); return
    if session.get('role', 'admin') != 'admin':
        emit('ssh_data', {'d': '\r\n[GL] SSH nur für Admins\r\n'}); return
    key = data.get('host', '')
    h   = STATIC_HOSTS.get(key)
    if not h or not h[4]:
        emit('ssh_data', {'d': f'\r\n[GL] Host "{key}" not found or not an LXC\r\n'}); return
    ip   = h[1]; name = h[0]
    sid  = request.sid
    user = session.get('username', '?')
    cols = data.get('cols', 220); rows = data.get('rows', 50)
    _audit(user, 'ssh_open', key, ip)

    ctid = h[4]
    ssh_user, ssh_pass = SSH_OVERRIDES.get(key, (LXC_SSH_USER, LXC_SSH_PASS))
    try:
        ssh = _paramiko.SSHClient()
        ssh.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
        if ctid and PROXMOX_PASS:
            # LXC port 22 is firewalled / root-login locked, so reach the container
            # through the Proxmox host (proven path) and `pct enter` into it.
            ssh.connect(PROXMOX_HOST, port=22, username='root', password=PROXMOX_PASS,
                        timeout=8, look_for_keys=False, allow_agent=False)
            chan = ssh.invoke_shell(term='xterm-256color', width=cols, height=rows)
            chan.settimeout(0)
            chan.send(f'pct enter {ctid}\n')
        else:
            ssh.connect(ip, port=22, username=ssh_user, password=ssh_pass,
                        timeout=8, look_for_keys=False, allow_agent=False)
            chan = ssh.invoke_shell(term='xterm-256color', width=cols, height=rows)
            chan.settimeout(0)
        with _ssh_sessions_lk:
            _ssh_sessions[sid] = (ssh, chan)

        banner = (f'\033[32m\r\n ╔══ GL Dashboard · SSH · {name} ══╗\r\n'
                  f' ║  {ip}  ·  user: {user}\r\n'
                  f' ╚══════════════════════════════════╝\033[0m\r\n\r\n')
        emit('ssh_data', {'d': banner})

        def _reader():
            while True:
                try:
                    if chan.recv_ready():
                        chunk = chan.recv(8192)
                        if not chunk: break
                        socketio.emit('ssh_data', {'d': chunk.decode('utf-8','replace')}, to=sid)
                    elif chan.closed or chan.exit_status_ready():
                        break
                except Exception:
                    break
                time.sleep(0.015)
            socketio.emit('ssh_data', {'d': '\r\n\033[33m[GL] Connection closed\033[0m\r\n'}, to=sid)
            with _ssh_sessions_lk:
                _ssh_sessions.pop(sid, None)
            _audit(user, 'ssh_close', key, ip)

        threading.Thread(target=_reader, daemon=True).start()

    except Exception as e:
        emit('ssh_data', {'d': f'\r\n\033[31m[GL] SSH failed: {e}\033[0m\r\n'})

@socketio.on('ssh_input')
def ws_ssh_input(data):
    with _ssh_sessions_lk:
        entry = _ssh_sessions.get(request.sid)
    if entry:
        try: entry[1].send(data.get('d', ''))
        except Exception: pass

@socketio.on('ssh_resize')
def ws_ssh_resize(data):
    with _ssh_sessions_lk:
        entry = _ssh_sessions.get(request.sid)
    if entry:
        try: entry[1].resize_pty(width=data.get('cols', 220), height=data.get('rows', 50))
        except Exception: pass

@socketio.on('disconnect')
def ws_disconnect():
    sid = request.sid
    with _ssh_sessions_lk:
        entry = _ssh_sessions.pop(sid, None)
    if entry:
        try: entry[1].close()
        except: pass
        try: entry[0].close()
        except: pass

@app.route('/api/crons')
@login_required
def api_crons_list():
    conn = sqlite3.connect(AUDIT_DB)
    rows = conn.execute('SELECT id,name,host_key,command,interval_min,enabled,created_at,last_run,last_ok,last_result,next_run,targets_json,schedule,last_results,created_by FROM crons ORDER BY created_at DESC').fetchall()
    conn.close()
    cols = ['id','name','host_key','command','interval_min','enabled','created_at','last_run','last_ok','last_result','next_run','targets_json','schedule','last_results','created_by']
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d['targets'] = json.loads(d.pop('targets_json') or '[]') or ([d['host_key']] if d.get('host_key') else [])
        except Exception:
            d['targets'] = []
        try:
            d['results'] = json.loads(d.pop('last_results') or '{}')
        except Exception:
            d['results'] = {}
        d['schedule'] = d.get('schedule') or 'manual'
        out.append(d)
    return jsonify(out)

@app.route('/api/crons/targets')
@login_required
def api_crons_targets():
    """Available target hosts (LXCs) for tasks."""
    meta = _get_host_meta()
    res = []
    for k in _all_lxc_targets():
        h = STATIC_HOSTS.get(k)
        name = (meta.get(k, {}).get('display_name')) or (h[0] if h else k)
        cat = (h[3] if h else '') or ''
        res.append({'key': k, 'name': name, 'category': cat})
    res.sort(key=lambda x: x['name'].lower())
    return jsonify(res)

@app.route('/api/crons', methods=['POST'])
@login_required
def api_crons_create():
    d = request.json or {}
    cmd = (d.get('command') or '').strip()
    targets = d.get('targets') or ([d['host_key']] if d.get('host_key') else [])
    if not cmd or not targets:
        return jsonify({'error': 'command und targets erforderlich'}), 400
    if "'" in cmd:
        return jsonify({'error': "Einfache Anführungszeichen (') werden derzeit nicht unterstützt"}), 400
    schedule = (d.get('schedule') or 'manual').strip()
    cid = str(_uuid.uuid4())[:8]
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('INSERT INTO crons (id,name,host_key,command,interval_min,enabled,created_at,next_run,targets_json,schedule,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                 (cid, d.get('name', 'Aufgabe'), '', cmd, int(d.get('interval_min', 60)),
                  1 if d.get('enabled', True) else 0, now, _schedule_next(schedule),
                  json.dumps(targets), schedule, _who()))
    conn.commit(); conn.close()
    _audit_user('task_create', '', f"{d.get('name','')} → {','.join(targets)[:80]} [{schedule}]")
    return jsonify({'id': cid, 'ok': True})

@app.route('/api/crons/<cron_id>', methods=['PATCH'])
@login_required
def api_crons_update(cron_id):
    d = request.json or {}
    conn = sqlite3.connect(AUDIT_DB)
    if 'enabled' in d:
        conn.execute('UPDATE crons SET enabled=? WHERE id=?', (int(bool(d['enabled'])), cron_id))
    if 'command' in d:
        conn.execute('UPDATE crons SET command=? WHERE id=?', (d['command'], cron_id))
    if 'name' in d:
        conn.execute('UPDATE crons SET name=? WHERE id=?', (d['name'], cron_id))
    if 'targets' in d:
        conn.execute('UPDATE crons SET targets_json=? WHERE id=?', (json.dumps(d['targets'] or []), cron_id))
    if 'schedule' in d:
        conn.execute('UPDATE crons SET schedule=?, next_run=? WHERE id=?',
                     (d['schedule'], _schedule_next(d['schedule']), cron_id))
    conn.commit(); conn.close()
    _audit_user('task_update', '', cron_id)
    return jsonify({'ok': True})

@app.route('/api/crons/<cron_id>', methods=['DELETE'])
@login_required
def api_crons_delete(cron_id):
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('DELETE FROM crons WHERE id=?', (cron_id,))
    conn.commit(); conn.close()
    _audit_user('task_delete', '', cron_id)
    return jsonify({'ok': True})

@app.route('/api/crons/<cron_id>/run', methods=['POST'])
@login_required
def api_crons_run(cron_id):
    who = _who()
    threading.Thread(target=_run_cron_job, args=(cron_id, who), daemon=True).start()
    _audit_user('task_run_manual', '', cron_id)
    return jsonify({'ok': True, 'msg': 'Gestartet'})

@app.route('/api/exec', methods=['POST'])
@login_required
def api_exec():
    """Ansible-Modus: einen Befehl SOFORT auf mehreren Hosts ausführen und die
    gesammelten Ausgaben zurückgeben (kein gespeicherter Cron-Job)."""
    d = request.json or {}
    cmd = (d.get('command') or '').strip()
    targets = d.get('targets') or []
    if not cmd:
        return jsonify({'error': 'command erforderlich'}), 400
    if "'" in cmd:
        return jsonify({'error': "Einfache Anführungszeichen (') werden derzeit nicht unterstützt"}), 400
    tg = _resolve_cron_targets(json.dumps(targets), '')
    if not tg:
        return jsonify({'error': 'Keine Ziel-Hosts gewählt'}), 400
    tg = tg[:40]  # Sicherheitslimit
    results, lock = {}, threading.Lock()

    def _worker(hk):
        t0 = time.time()
        vmid = _host_vmid(hk)
        if not vmid:
            r = {'ok': False, 'out': 'keine VMID (kein LXC erreichbar)', 'ms': 0}
        else:
            try:
                out = _prox_exec(vmid, cmd, timeout=120)
                r = {'ok': 'command not found' not in out.lower(),
                     'out': out.strip()[-6000:], 'ms': int((time.time() - t0) * 1000)}
            except Exception as ex:
                r = {'ok': False, 'out': str(ex)[:500], 'ms': int((time.time() - t0) * 1000)}
        with lock:
            results[hk] = r

    threads = [threading.Thread(target=_worker, args=(hk,), daemon=True) for hk in tg]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=130)
    ok_n = sum(1 for r in results.values() if r.get('ok'))
    _audit_user('exec_adhoc', ','.join(tg)[:80], f'{cmd[:60]} → {ok_n}/{len(tg)} OK')
    return jsonify({'results': results, 'summary': f'{ok_n}/{len(results)} OK', 'command': cmd})

# ─── ERSTEINRICHTUNG, HOSTS, NETZWERK-SCAN, AGENT-INSTALLER ──────────────
BRAND = os.environ.get('BRAND_NAME', 'RRM')

@app.context_processor
def _inject_brand():
    return {'brand': BRAND, 'sso': oidc_enabled(), 'sso_name': OIDC_NAME, 'sso_only': OIDC_ONLY and oidc_enabled()}

def _user_count():
    _users_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    n = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()
    return n

@app.route('/setup', methods=['GET', 'POST'])
def setup_page():
    # Nur solange noch kein Benutzer existiert.
    if _user_count() > 0:
        return redirect(url_for('login_page'))
    error = None
    if request.method == 'POST':
        u  = request.form.get('username', '').strip().lower()
        p  = request.form.get('password', '')
        p2 = request.form.get('password2', '')
        if not re.fullmatch(r'[a-z0-9._-]{2,32}', u):
            error = 'Benutzername: 2–32 Zeichen (a–z, 0–9, . _ -)'
        elif len(p) < 10:
            error = 'Passwort muss mindestens 10 Zeichen haben'
        elif p != p2:
            error = 'Passwörter stimmen nicht überein'
        else:
            conn = sqlite3.connect(AUDIT_DB)
            conn.execute('INSERT INTO users (username,pw_hash,role,created_at) VALUES (?,?,?,?)',
                         (u, generate_password_hash(p), 'admin', time.strftime('%Y-%m-%dT%H:%M:%S')))
            conn.commit(); conn.close()
            _audit(u, 'setup', '', 'Administrator bei Ersteinrichtung angelegt')
            return redirect(url_for('login_page'))
    return render_template('setup.html', error=error)

def _hub_url():
    base = os.environ.get('DASHBOARD_URL', '').rstrip('/')
    return base or request.host_url.rstrip('/')

@app.route('/agent/gl-agent.py')
def agent_download():
    # Der Agent enthaelt keine Geheimnisse; das Token wird bei der Installation gesetzt.
    return send_from_directory(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent'),
                               'gl-agent.py', mimetype='text/x-python')

_INSTALL_SH = r'''#!/bin/sh
# Installiert den RRM-Agent (nur Python 3, keine Pakete). Aufruf:
#   curl -fsSL __HUB__/agent/install.sh | GL_TOKEN=<agent-token> sh
set -e
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren"; exit 1; }
[ -n "$GL_TOKEN" ] || { echo "GL_TOKEN fehlt"; exit 1; }
command -v python3 >/dev/null || { echo "python3 nicht gefunden"; exit 1; }
curl -fsSL "__HUB__/agent/gl-agent.py" -o /opt/gl-agent.py
chmod 755 /opt/gl-agent.py
umask 077
cat > /etc/gl-agent.env <<ENV
GL_AGENT_TOKEN=$GL_TOKEN
GL_HUB_URL=__HUB__
GL_REGISTER=1
GL_REGISTER_INTERVAL=60
ENV
cat > /etc/systemd/system/gl-agent.service <<'UNIT'
[Unit]
Description=RRM Agent
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/usr/bin/python3 /opt/gl-agent.py
EnvironmentFile=/etc/gl-agent.env
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now gl-agent
echo "RRM-Agent laeuft. Der Host erscheint im Dashboard innerhalb einer Minute."
'''

@app.route('/agent/install.sh')
def agent_install_script():
    return app.response_class(_INSTALL_SH.replace('__HUB__', _hub_url()), mimetype='text/x-shellscript')

@app.route('/api/connect')
@login_required
def api_connect():
    hub = _hub_url()
    return jsonify({
        'hub_url':    hub,
        'agent_token': GL_AGENT_TOKEN,
        'mcp_token':  MCP_TOKEN,
        'mcp_url':    f'{hub}/mcp',
        'agents':     sum(1 for a in _agents_list() if not a['stale']),
        'install_cmd': f'curl -fsSL {hub}/agent/install.sh | GL_TOKEN={GL_AGENT_TOKEN} sh',
        'mcp_cmd':    f'claude mcp add --transport http rrm {hub}/mcp --header "Authorization: Bearer {MCP_TOKEN}"',
        'integrations': {
            'proxmox': bool(PROXMOX_HOST and (PROXMOX_TOKEN or PROXMOX_PASS)),
            'unifi':   bool(UNIFI_URL and UNIFI_USER),
            'prometheus': bool(PROMETHEUS), 'loki': bool(LOKI_URL), 'grafana': bool(GRAFANA_URL),
            'dokploy': bool(DOKPLOY_URL and DOKPLOY_KEY), 'coolify': bool(COOLIFY_URL and COOLIFY_KEY),
            'litellm': bool(LITELLM_URL and LITELLM_KEY), 'ai': ai_ready(), 'ai_provider': ai_provider(),
            'telegram': bool(TELEGRAM_TOKEN),
        },
    })

def _host_key(ip):
    return 'host-' + ip.replace('.', '-')

@app.route('/api/hosts', methods=['POST'])
@admin_required
def api_hosts_add():
    import ipaddress
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()[:60]
    ip = (d.get('ip') or '').strip()
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return jsonify({'ok': False, 'error': 'Ungültige IP-Adresse'}), 400
    if any(v[1] == ip for v in STATIC_HOSTS.values()):
        return jsonify({'ok': False, 'error': 'Host ist bereits bekannt'}), 409
    key = _host_key(ip)
    _manual_hosts_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('INSERT OR REPLACE INTO manual_hosts (key,name,ip,created) VALUES (?,?,?,?)',
                 (key, name or ip, ip, int(time.time())))
    conn.commit(); conn.close()
    STATIC_HOSTS[key] = (name or ip, ip, '🖥️', 'app', None, [])
    cache.bust('live')
    _audit_user('host_add', key, f'{name or ip} ({ip})')
    return jsonify({'ok': True, 'key': key})

@app.route('/api/hosts/<key>', methods=['DELETE'])
@admin_required
def api_hosts_delete(key):
    _manual_hosts_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    n = conn.execute('DELETE FROM manual_hosts WHERE key=?', (key,)).rowcount
    conn.commit(); conn.close()
    if not n:
        return jsonify({'ok': False, 'error': 'Nur manuell hinzugefügte Hosts können entfernt werden'}), 400
    STATIC_HOSTS.pop(key, None)
    cache.bust('live')
    _audit_user('host_remove', key, '')
    return jsonify({'ok': True})

def _default_cidr():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.0.2.1', 9))
        ip = s.getsockname()[0]; s.close()
        return '.'.join(ip.split('.')[:3]) + '.0/24'
    except Exception:
        return '192.168.0.0/24'

@app.route('/api/scan', methods=['GET', 'POST'])
@admin_required
def api_scan():
    """Ping-Sweep eines privaten Netzes; liefert erreichbare Hosts mit Namen und offenen Ports."""
    import ipaddress
    if request.method == 'GET':
        return jsonify({'default_cidr': _default_cidr()})
    cidr = ((request.get_json(silent=True) or {}).get('cidr') or _default_cidr()).strip()
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return jsonify({'ok': False, 'error': 'Ungültiges Netz (Beispiel: 192.168.1.0/24)'}), 400
    if not net.is_private or net.num_addresses > 1024:
        return jsonify({'ok': False, 'error': 'Nur private Netze bis /22 erlaubt'}), 400
    ips = [str(i) for i in net.hosts()]
    known = {v[1] for v in STATIC_HOSTS.values()}
    def probe(ip):
        r = _ping(ip)
        if not (r and r[1]):
            return None
        try:
            name = socket.gethostbyaddr(ip)[0]
        except Exception:
            name = ''
        return {'ip': ip, 'name': name, 'rtt': r[0], 'known': ip in known, 'ports': scan_ports_fast(ip, 0.25)}
    with ThreadPoolExecutor(max_workers=64) as pool:
        found = [x for x in pool.map(probe, ips) if x]
    _audit_user('network_scan', '', f'{cidr}: {len(found)} Hosts')
    return jsonify({'ok': True, 'cidr': str(net), 'hosts': found})

# ─── EINSTELLUNGEN AUS DER OBERFLAECHE ───────────────────────────────────
CONFIG_FIELDS = [
    ('Allgemein', [
        ('BRAND_NAME', 'Anzeigename', False, 'z.B. Goetschi Control'),
        ('DASHBOARD_URL', 'Adresse des Dashboards', False, 'http://10.0.0.5:8181'),
    ]),
    ('Telegram-Alarme', [
        ('TELEGRAM_TOKEN', 'Bot-Token', True, 'von @BotFather'),
        ('TELEGRAM_CHAT_ID', 'Chat-ID', False, 'z.B. 123456789'),
    ]),
    ('Proxmox', [
        ('PROXMOX_HOST', 'Host', False, '10.0.0.10'),
        ('PROXMOX_TOKEN', 'API-Token', True, 'user@pve!name=secret'),
        ('PROXMOX_NODE', 'Node (leer = automatisch)', False, ''),
    ]),
    ('UniFi', [
        ('UNIFI_URL', 'Adresse', False, 'https://10.0.0.1'),
        ('UNIFI_USER', 'Benutzer', False, ''),
        ('UNIFI_PASS', 'Passwort', True, ''),
    ]),
    ('KI', [
        ('AI_PROVIDER', 'Anbieter: agy (Antigravity) oder litellm', False, 'agy'),
        ('AI_AUTONOMY', 'Selbstständigkeit: off | report | full (full = handelt selbst mit Root)', False, 'report'),
        ('AI_ALERTS', 'Auf neue Alarme reagieren: 1 = ja, 0 = nein', False, '1'),
        ('LITELLM_URL', 'LiteLLM-Adresse (nur bei litellm)', False, 'http://10.0.0.20:4000'),
        ('LITELLM_KEY', 'API-Key', True, ''),
        ('LLM_MODEL', 'Modell (leer = erstes verfügbares)', False, ''),
    ]),
    ('GitHub (KI-Entwicklung)', [
        ('GITHUB_REPO', 'Repository (owner/name)', False, 'GoetschiM/goetschi-control'),
        ('GITHUB_TOKEN', 'Token mit Contents + Pull requests: Read and write', True, 'github_pat_…'),
    ]),
    ('Logs & Metriken', [
        ('LOKI_URL', 'Loki', False, 'http://127.0.0.1:3100'),
        ('PROMETHEUS_URL', 'Prometheus', False, ''),
        ('GRAFANA_URL', 'Grafana', False, ''),
    ]),
    ('Deployment', [
        ('DOKPLOY_URL', 'Dokploy-Adresse', False, ''),
        ('DOKPLOY_API_KEY', 'Dokploy-API-Key', True, ''),
        ('COOLIFY_URL', 'Coolify-Adresse', False, ''),
        ('COOLIFY_API_KEY', 'Coolify-API-Key', True, ''),
    ]),
    ('Single Sign-on (OIDC)', [
        ('OIDC_ISSUER', 'Issuer-URL', False, 'https://auth.example.com/application/o/rrm'),
        ('OIDC_CLIENT_ID', 'Client-ID', False, ''),
        ('OIDC_CLIENT_SECRET', 'Client-Secret', True, ''),
        ('OIDC_NAME', 'Button-Text', False, 'Authentik'),
        ('OIDC_ADMIN_GROUP', 'Admin-Gruppe', False, 'rrm-admins'),
    ]),
]
_CONFIG_KEYS = {k: secret for _, fs in CONFIG_FIELDS for k, _, secret, _ in fs}

@app.route('/api/config', methods=['GET', 'POST'])
@admin_required
def api_config():
    overrides = _read_config_file()
    if request.method == 'GET':
        groups = []
        for g, fs in CONFIG_FIELDS:
            items = []
            for k, label, secret, hint in fs:
                v = overrides[k] if k in overrides else os.environ.get(k, '')
                items.append({'key': k, 'label': label, 'secret': secret, 'hint': hint, 'set': bool(v),
                              'value': '' if secret else v, 'source': 'ui' if k in overrides else ('env' if v else '')})
            groups.append({'name': g, 'fields': items})
        return jsonify({'groups': groups, 'restart_pending': _config_dirty['v']})
    d = (request.get_json(silent=True) or {}).get('values') or {}
    changed = []
    for k, v in d.items():
        if k not in _CONFIG_KEYS:
            return jsonify({'ok': False, 'error': f'Unbekannte Einstellung: {k}'}), 400
        v = str(v).replace('\n', '').replace('\r', '').strip()
        if _CONFIG_KEYS[k] and v == '':
            continue            # leeres Geheimnis-Feld = unveraendert lassen
        overrides[k] = v
        changed.append(k)
    if changed:
        tmp = CONFIG_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write('# Von der Oberflaeche verwaltet. Vorrang vor der Umgebung.\n')
            for k, v in overrides.items():
                f.write(f'{k}={v}\n')
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG_FILE)
        _config_dirty['v'] = True
        _audit_user('config_change', '', ', '.join(changed))
    return jsonify({'ok': True, 'changed': changed, 'restart_pending': _config_dirty['v']})

_config_dirty = {'v': False}

@app.route('/api/config/clear', methods=['POST'])
@admin_required
def api_config_clear():
    k = (request.get_json(silent=True) or {}).get('key')
    if k not in _CONFIG_KEYS:
        return jsonify({'ok': False, 'error': 'Unbekannte Einstellung'}), 400
    overrides = _read_config_file()
    overrides[k] = ''
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        f.write('# Von der Oberflaeche verwaltet. Vorrang vor der Umgebung.\n')
        for kk, v in overrides.items():
            f.write(f'{kk}={v}\n')
    os.chmod(CONFIG_FILE, 0o600)
    _config_dirty['v'] = True
    _audit_user('config_change', '', f'{k} geleert')
    return jsonify({'ok': True})

@app.route('/api/app/restart', methods=['POST'])
@admin_required
def api_app_restart():
    """Beendet den Prozess; systemd bzw. Docker starten ihn mit der neuen Konfiguration neu."""
    _audit_user('app_restart', '', 'Neustart fuer neue Einstellungen')
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return jsonify({'ok': True})

# ─── AGENT- UND DOCKER-VERWALTUNG UEBER DEN AGENT ────────────────────────
def _agent_call(ip, path, body=None, timeout=60):
    req = urllib.request.Request(f'http://{ip}:{AGENT_PORT}{path}',
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method='POST' if body is not None else 'GET')
    req.add_header('Authorization', f'Bearer {_agent_token(ip)}')
    req.add_header('Content-Type', 'application/json')
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {'ok': False, 'error': f'Agent: HTTP {e.code}'}
    except Exception as e:
        return {'ok': False, 'error': f'Agent nicht erreichbar: {e}'}

def _host_ip(host_key):
    h = STATIC_HOSTS.get(host_key)
    if h:
        return h[1]
    for x in (cache.get('live') or {}).get('hosts', []):
        if x.get('key') == host_key:
            return x.get('ip')
    return None

@app.route('/api/agent-admin/<host_key>/<action>', methods=['POST'])
@admin_required
def api_agent_admin(host_key, action):
    ip = _host_ip(host_key)
    if not ip:
        return jsonify({'ok': False, 'error': 'Host unbekannt'}), 404
    if action == 'update':
        r = _agent_call(ip, '/update', {'url': f'{_hub_url()}/agent/gl-agent.py'})
    elif action == 'uninstall':
        if not (request.get_json(silent=True) or {}).get('confirm'):
            return jsonify({'ok': False, 'error': 'Bestätigung fehlt'}), 400
        r = _agent_call(ip, '/uninstall', {'confirm': True})
    else:
        return jsonify({'ok': False, 'error': 'Unbekannte Aktion'}), 400
    _audit_user('agent_' + action, host_key, r.get('msg') or r.get('error') or '')
    cache.bust()
    return jsonify(r)

@app.route('/api/docker/<host_key>/policies')
@login_required
def api_docker_policies(host_key):
    ip = _host_ip(host_key)
    return jsonify(_agent_call(ip, '/docker/policies', timeout=20) if ip else {})

@app.route('/api/docker/<host_key>/action', methods=['POST'])
@admin_required
def api_docker_action(host_key):
    ip = _host_ip(host_key)
    d = request.get_json(silent=True) or {}
    if not ip:
        return jsonify({'ok': False, 'error': 'Host unbekannt'}), 404
    r = _agent_call(ip, '/docker/action', {'name': d.get('name', ''), 'action': d.get('action', ''),
                                           'confirm': bool(d.get('confirm'))})
    if r.get('error') == 'Not found':
        r = {'ok': False, 'error': 'Agent zu alt – bitte zuerst den Agent aktualisieren'}
    _audit_user('docker_' + str(d.get('action')), host_key, f"{d.get('name')}: {r.get('msg') or r.get('error')}")
    cache.bust()
    return jsonify(r)

# ── Proxmox-Backups und Autostart ueber die API (Token braucht dafuer passende Rechte) ──
def _px_write(method, path, data):
    if not (PROXMOX_HOST and PROXMOX_TOKEN):
        return {'ok': False, 'error': 'PROXMOX_TOKEN fehlt'}
    _ensure_node()
    req = urllib.request.Request(f'{PROXMOX_API}{path}', data=urllib.parse.urlencode(data).encode(), method=method)
    req.add_header('Authorization', f'PVEAPIToken={PROXMOX_TOKEN}')
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=15, context=_ssl_ctx).read())
        return {'ok': True, 'data': d.get('data')}
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf-8', 'replace')[:200]
        if e.code == 403:
            msg = 'Proxmox-Token hat dafür keine Rechte (z.B. Rolle PVEVMAdmin + Datastore.AllocateSpace)'
        return {'ok': False, 'error': msg}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@app.route('/api/pve/storages')
@login_required
def api_pve_storages():
    _ensure_node()
    d = _px(f'/nodes/{PROXMOX_NODE}/storage?content=backup') or {}
    return jsonify([{'storage': s.get('storage'), 'avail_gb': round((s.get('avail') or 0) / 2**30, 1),
                     'active': bool(s.get('active'))} for s in d.get('data', []) if s.get('active')])

@app.route('/api/pve/<int:vmid>/backup', methods=['POST'])
@admin_required
def api_pve_backup(vmid):
    d = request.get_json(silent=True) or {}
    storage = d.get('storage') or 'local'
    r = _px_write('POST', f'/nodes/{PROXMOX_NODE}/vzdump',
                  {'vmid': vmid, 'storage': storage, 'mode': 'snapshot', 'compress': 'zstd',
                   'notes-template': f'RRM-Backup {{{{guestname}}}}'})
    _audit_user('pve_backup', f'ct{vmid}', f"{storage}: {'gestartet' if r['ok'] else r['error']}")
    return jsonify(r if not r['ok'] else {'ok': True, 'msg': f'Backup von {vmid} nach {storage} gestartet', 'task': r['data']})

@app.route('/api/pve/<int:vmid>/onboot', methods=['POST'])
@admin_required
def api_pve_onboot(vmid):
    on = bool((request.get_json(silent=True) or {}).get('on'))
    kind = 'qemu' if (request.get_json(silent=True) or {}).get('type') == 'qemu' else 'lxc'
    r = _px_write('PUT', f'/nodes/{PROXMOX_NODE}/{kind}/{vmid}/config', {'onboot': 1 if on else 0})
    _audit_user('pve_onboot', f'ct{vmid}', f"{'an' if on else 'aus'}: {'ok' if r['ok'] else r['error']}")
    return jsonify(r)

@app.route('/api/pve/<int:vmid>/info')
@login_required
def api_pve_info(vmid):
    _ensure_node()
    cfg = (_px(f'/nodes/{PROXMOX_NODE}/lxc/{vmid}/config') or {}).get('data') or {}
    bk = (_px(f'/nodes/{PROXMOX_NODE}/tasks?typefilter=vzdump&vmid={vmid}&limit=5') or {}).get('data') or []
    return jsonify({'onboot': bool(int(cfg.get('onboot', 0) or 0)),
                    'backups': [{'start': t.get('starttime'), 'status': t.get('status')} for t in bk]})

# ─── KI-ASSISTENT: Antigravity CLI (agy) ─────────────────────────────────
# Jede Frage laeuft zuerst im Plan-Modus (nur lesen und vorschlagen). Ausgefuehrt wird erst,
# wenn ein Admin im Gespraech auf "Ausfuehren" klickt. Alles wird im Protokoll festgehalten.
AGY_BIN     = os.environ.get('AGY_BIN', '/usr/local/bin/agy')
AGY_WORKDIR = os.environ.get('AGY_WORKDIR', '/root/admin')
AGY_HOME    = os.environ.get('AGY_HOME', '/root')
AGY_TIMEOUT = int(os.environ.get('AGY_TIMEOUT', '600'))
_agy_lock = threading.Lock()

def agy_available():
    return os.path.exists(AGY_BIN)

def ai_provider():
    p = os.environ.get('AI_PROVIDER', '').strip().lower()
    if p in ('agy', 'litellm'):
        return p
    return 'agy' if agy_available() else 'litellm'

def ai_ready():
    return agy_available() if ai_provider() == 'agy' else bool(LITELLM_URL and LITELLM_KEY)

def _agy_run(prompt, conversation=None, execute=False, timeout=None):
    # Ein Turn von agy. execute=False: nur was in der agy-Freigabeliste steht (lesende
    # RRM-Werkzeuge per MCP), alles andere wird abgelehnt. execute=True: volle Rechte.
    t = timeout or AGY_TIMEOUT
    cmd = [AGY_BIN, '-p', prompt, '--output-format', 'json', '--print-timeout', f'{t}s']
    if execute:
        cmd += ['--dangerously-skip-permissions']
    if conversation:
        cmd += ['--conversation', conversation]
    env = dict(os.environ, HOME=AGY_HOME, PATH='/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin')
    if os.environ.get('GITHUB_TOKEN'):
        env['GH_TOKEN'] = os.environ['GITHUB_TOKEN']   # fuer gh/git im Ausfuehren-Modus
    os.makedirs(AGY_WORKDIR, exist_ok=True)
    with _agy_lock:
        r = subprocess.run(cmd, cwd=AGY_WORKDIR, env=env, capture_output=True, text=True, timeout=t + 30)
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {'ok': False, 'error': (r.stderr or r.stdout or 'keine Ausgabe von agy')[-500:]}
    answer = (d.get('response') or '').strip()
    # agy meldet gelegentlich status=ERROR trotz vollstaendiger Antwort -> Antwort zaehlt
    ok = d.get('status') == 'SUCCESS' or bool(answer)
    denied = [a.get('display_name') or a.get('action') for a in (d.get('denied_actions') or [])]
    if denied:
        note = ('Für diesen Schritt brauchte ich Rechte, die im Fragemodus gesperrt sind ('
                + ', '.join(sorted(set(denied))) + '). Mit „Plan ausführen“ gibst du sie frei.')
        answer = f'{answer}\n\n{note}' if answer else note
    return {'ok': ok, 'answer': answer, 'denied': denied, 'conversation_id': d.get('conversation_id'),
            'duration': d.get('duration_seconds'), 'error': None if ok else d.get('status')}

def _ai_db():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS ai_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT, role TEXT, mode TEXT,
        text TEXT, user TEXT, host_key TEXT, ts INTEGER)''')
    conn.commit()
    return conn

def _ai_log(conv, role, mode, text, user, host_key=None):
    conn = _ai_db()
    conn.execute('INSERT INTO ai_messages (conversation,role,mode,text,user,host_key,ts) VALUES (?,?,?,?,?,?,?)',
                 (conv, role, mode, text, user, host_key, int(time.time())))
    conn.commit(); conn.close()

_AGY_FIRST_PROMPT = (
    'Du arbeitest im {brand} (RRM) auf diesem Container. Halte dich an RRM.md (und AGENTS.md, falls vorhanden) '
    'in deinem Arbeitsordner. '
    'Aktueller Kurzstatus aus dem Dashboard:\n{ctx}\n\n'
    'Antworte auf Deutsch, knapp und konkret. Wenn eine Aenderung noetig ist, beschreibe sie als '
    'nummerierten Plan (was, wo, Risiko, wie rueckgaengig). In diesem Schritt darfst du nur lesen: '
    'nutze die rrm-Werkzeuge (list_containers, infra_status, list_agents, active_alerts, find_package). '
    'Ausgefuehrt wird erst, wenn der Benutzer den Plan freigibt.\n\n'
    'FRAGE{host}: {q}'
)

@app.route('/api/ai/status')
@login_required
def api_ai_status():
    return jsonify({'provider': ai_provider(), 'ready': ai_ready(), 'agy': agy_available(),
                    'busy': _agy_lock.locked()})

@app.route('/api/ai/conversations')
@login_required
def api_ai_conversations():
    conv = request.args.get('id', '')
    conn = _ai_db()
    if conv:
        rows = conn.execute('SELECT role,mode,text,user,ts FROM ai_messages WHERE conversation=? ORDER BY id', (conv,)).fetchall()
        conn.close()
        return jsonify([{'role': r[0], 'mode': r[1], 'text': r[2], 'user': r[3], 'ts': r[4]} for r in rows])
    rows = conn.execute('''SELECT conversation, MAX(ts),
        (SELECT text FROM ai_messages m2 WHERE m2.conversation=m.conversation AND role='user' ORDER BY id LIMIT 1)
        FROM ai_messages m WHERE conversation IS NOT NULL GROUP BY conversation ORDER BY MAX(ts) DESC LIMIT 30''').fetchall()
    conn.close()
    return jsonify([{'id': r[0], 'last': r[1], 'title': (r[2] or '')[:90]} for r in rows])

# ─── KI-UEBERWACHUNG: Pruefungen, Alarm-Reaktion, Selbststaendigkeit ─────
# AI_AUTONOMY: off | report | full
#   report = Antigravity untersucht und meldet, aendert nichts (nur lesende Werkzeuge)
#   full   = Antigravity darf bei Pruefungen und Alarmen selbst handeln (Root). Jede Aktion
#            wird protokolliert und per Telegram gemeldet.
def ai_autonomy():
    v = os.environ.get('AI_AUTONOMY', 'report').strip().lower()
    return v if v in ('off', 'report', 'full') else 'report'

def _mon_db():
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS ai_monitors (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, prompt TEXT, interval_min INTEGER,
        enabled INTEGER DEFAULT 1, created_by TEXT, created INTEGER,
        last_run INTEGER, last_status TEXT, last_result TEXT, conversation TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS ai_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref TEXT, ts INTEGER, status TEXT,
        mode TEXT, result TEXT, conversation TEXT)''')
    conn.commit()
    return conn

def _ai_run_log(kind, ref, status, mode, result, conv):
    conn = _mon_db()
    conn.execute('INSERT INTO ai_runs (kind,ref,ts,status,mode,result,conversation) VALUES (?,?,?,?,?,?,?)',
                 (kind, ref, int(time.time()), status, mode, (result or '')[:6000], conv))
    conn.execute('DELETE FROM ai_runs WHERE id NOT IN (SELECT id FROM ai_runs ORDER BY id DESC LIMIT 500)')
    conn.commit(); conn.close()

def _auto_prompt(title, task, full):
    rules = ('Du darfst selbst handeln (volle Rechte). Bevorzuge die rrm-admin-Werkzeuge. Nichts loeschen '
             'ausser es ist eindeutig noetig und rueckgaengig machbar. Berichte genau, was du geaendert hast '
             'und wie man es rueckgaengig macht.') if full else \
            'Du darfst nur lesen (rrm-Werkzeuge). Aendere nichts, sondern schlage einen konkreten Plan vor.'
    return (f'Automatische Aufgabe "{title}". Halte dich an RRM.md. {rules}\n'
            f'Aufgabe: {task}\n'
            'Erste Zeile deiner Antwort exakt: STATUS: OK oder STATUS: PROBLEM oder STATUS: BEHOBEN. '
            'Danach kurz Befund, Ursache und (falls noetig) Massnahme.')

def _parse_status(text, ok):
    if not ok:
        return 'error'
    t = (text or '').upper()
    for k, v in (('STATUS: BEHOBEN', 'fixed'), ('STATUS: PROBLEM', 'problem'), ('STATUS: OK', 'ok')):
        if k in t:
            return v
    return 'ok'

def _notify(title, status, text):
    icon = {'problem': '⚠️', 'fixed': '🛠️', 'error': '❌'}.get(status)
    if icon:
        try:
            _tg_send(f'{icon} *{BRAND} · {title}*\n{(text or "")[:1200]}')
        except Exception:
            pass

def run_monitor(mid, manual=False):
    conn = _mon_db()
    row = conn.execute('SELECT name,prompt,last_status FROM ai_monitors WHERE id=?', (mid,)).fetchone()
    conn.close()
    if not row or not agy_available() or (ai_autonomy() == 'off' and not manual):
        return None
    full = ai_autonomy() == 'full'
    try:
        r = _agy_run(_auto_prompt(row[0], row[1], full), execute=full)
    except Exception as e:
        r = {'ok': False, 'error': str(e)}
    text = r.get('answer') or f"Fehler: {r.get('error')}"
    st = _parse_status(text, r.get('ok'))
    conn = _mon_db()
    conn.execute('UPDATE ai_monitors SET last_run=?, last_status=?, last_result=?, conversation=? WHERE id=?',
                 (int(time.time()), st, text[:6000], r.get('conversation_id'), mid))
    conn.commit(); conn.close()
    _ai_run_log('monitor', row[0], st, 'full' if full else 'report', text, r.get('conversation_id'))
    if st != row[2] or st == 'fixed':
        _notify(row[0], st, text)
    if full:
        _audit('ki', 'monitor_run', '', f'{row[0]}: {st}')
    return st

_alert_seen = {}   # Signatur -> letzter Lauf

def _react_to_alerts():
    # Neue Alarme: einmal pro Signatur und 6 Stunden, hoechstens 4 Laeufe pro Stunde.
    if ai_autonomy() == 'off' or not agy_available() or os.environ.get('AI_ALERTS', '1') == '0':
        return
    alerts = (cache.get('live') or {}).get('alerts') or []
    now = time.time()
    recent = sum(1 for t in _alert_seen.values() if now - t < 3600)
    for a in alerts:
        # Zahlen im Text ignorieren ("Disk voll in ~6.0d" vs "~6.1d" ist derselbe Alarm)
        sig = f"{a.get('key')}|{re.sub(r'[0-9.,~%]+', '#', a.get('msg') or '')}"
        if now - _alert_seen.get(sig, 0) < 6 * 3600 or recent >= 4:
            continue
        _alert_seen[sig] = now; recent += 1
        full = ai_autonomy() == 'full'
        task = (f"Neuer Alarm ({a.get('severity')}): {a.get('host')} ({a.get('ip')}) – {a.get('msg')}. "
                'Finde die Ursache (Status, Logs, Docker).' + (' Behebe sie, wenn das sicher moeglich ist.' if full else ''))
        try:
            r = _agy_run(_auto_prompt(f"Alarm {a.get('host')}", task, full), execute=full)
        except Exception as e:
            r = {'ok': False, 'error': str(e)}
        text = r.get('answer') or f"Fehler: {r.get('error')}"
        st = _parse_status(text, r.get('ok'))
        _ai_run_log('alert', f"{a.get('host')}: {a.get('msg')}", st, 'full' if full else 'report', text, r.get('conversation_id'))
        _notify(f"Alarm {a.get('host')}", 'problem' if st == 'ok' else st, text)
        if full:
            _audit('ki', 'alert_reaction', a.get('key') or '', f"{a.get('msg')}: {st}")

def _ai_bg():
    time.sleep(120)
    while True:
        try:
            if agy_available() and ai_autonomy() != 'off':
                conn = _mon_db()
                due = conn.execute('SELECT id FROM ai_monitors WHERE enabled=1 AND '
                                   '(last_run IS NULL OR last_run + interval_min*60 <= ?)', (int(time.time()),)).fetchall()
                conn.close()
                for (mid,) in due:
                    run_monitor(mid)
                _react_to_alerts()
        except Exception as e:
            print(f'[ki] {e}')
        time.sleep(60)

def monitor_create(name, prompt, interval_min, user):
    name = (name or '').strip()[:80]; prompt = (prompt or '').strip()[:2000]
    if not name or not prompt:
        raise ValueError('Name und Aufgabe sind nötig')
    interval_min = max(5, min(int(interval_min or 60), 10080))
    conn = _mon_db()
    cur = conn.execute('INSERT INTO ai_monitors (name,prompt,interval_min,created_by,created) VALUES (?,?,?,?,?)',
                       (name, prompt, interval_min, user, int(time.time())))
    conn.commit(); mid = cur.lastrowid; conn.close()
    _audit(user, 'monitor_create', '', f'{name} alle {interval_min} min')
    return mid

def monitors_list():
    conn = _mon_db()
    rows = conn.execute('SELECT id,name,prompt,interval_min,enabled,created_by,created,last_run,last_status,last_result '
                        'FROM ai_monitors ORDER BY id').fetchall()
    conn.close()
    return [{'id': r[0], 'name': r[1], 'prompt': r[2], 'interval_min': r[3], 'enabled': bool(r[4]),
             'created_by': r[5], 'created': r[6], 'last_run': r[7], 'last_status': r[8], 'last_result': r[9]} for r in rows]

def _system_crons():
    # Geplante Aufgaben dieses Servers ausserhalb des RRM (crontab, cron.d, systemd-Timer) – nur Anzeige.
    out = {}
    try:
        out['crontab_root'] = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        out['crontab_root'] = ''
    try:
        out['cron_d'] = {f: open(os.path.join('/etc/cron.d', f)).read()[:2000]
                         for f in sorted(os.listdir('/etc/cron.d')) if not f.startswith('.')}
    except Exception:
        out['cron_d'] = {}
    try:
        out['timers'] = subprocess.run(['systemctl', 'list-timers', '--all', '--no-pager', '--no-legend'],
                                       capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        out['timers'] = ''
    return out

@app.route('/api/monitors', methods=['GET', 'POST'])
@login_required
def api_monitors():
    if request.method == 'GET':
        conn = _mon_db()
        runs = conn.execute('SELECT kind,ref,ts,status,mode,result FROM ai_runs ORDER BY id DESC LIMIT 40').fetchall()
        conn.close()
        return jsonify({'monitors': monitors_list(), 'autonomy': ai_autonomy(), 'agy': agy_available(),
                        'telegram': bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
                        'runs': [{'kind': r[0], 'ref': r[1], 'ts': r[2], 'status': r[3], 'mode': r[4], 'result': r[5]} for r in runs],
                        'system': _system_crons()})
    if session.get('role', 'admin') != 'admin':
        return jsonify({'ok': False, 'error': 'Nur Admins'}), 403
    d = request.get_json(silent=True) or {}
    try:
        mid = monitor_create(d.get('name'), d.get('prompt'), d.get('interval_min'), session.get('username', '?'))
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    return jsonify({'ok': True, 'id': mid})

@app.route('/api/monitors/<int:mid>', methods=['PATCH', 'DELETE'])
@admin_required
def api_monitor_edit(mid):
    conn = _mon_db()
    if request.method == 'DELETE':
        conn.execute('DELETE FROM ai_monitors WHERE id=?', (mid,))
        _audit_user('monitor_delete', '', str(mid))
    else:
        d = request.get_json(silent=True) or {}
        if 'enabled' in d:
            conn.execute('UPDATE ai_monitors SET enabled=? WHERE id=?', (1 if d['enabled'] else 0, mid))
        if 'interval_min' in d:
            conn.execute('UPDATE ai_monitors SET interval_min=? WHERE id=?', (max(5, int(d['interval_min'])), mid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/monitors/<int:mid>/run', methods=['POST'])
@admin_required
def api_monitor_run(mid):
    if _agy_lock.locked():
        return jsonify({'ok': False, 'error': 'Antigravity ist gerade beschäftigt'}), 409
    threading.Thread(target=run_monitor, args=(mid, True), daemon=True).start()
    return jsonify({'ok': True})

# ─── SSO (OpenID Connect: Authentik, Keycloak, Entra ID, Google, …) ───────
OIDC_ISSUER        = os.environ.get('OIDC_ISSUER', '').rstrip('/')
OIDC_CLIENT_ID     = os.environ.get('OIDC_CLIENT_ID', '')
OIDC_CLIENT_SECRET = os.environ.get('OIDC_CLIENT_SECRET', '')
OIDC_NAME          = os.environ.get('OIDC_NAME', 'SSO')
OIDC_ADMIN_GROUP   = os.environ.get('OIDC_ADMIN_GROUP', '')      # Mitglieder werden Admin
OIDC_DEFAULT_ROLE  = os.environ.get('OIDC_DEFAULT_ROLE', 'viewer')
OIDC_ONLY          = os.environ.get('OIDC_ONLY', '0') == '1'     # Passwort-Login ausblenden

def oidc_enabled():
    return bool(OIDC_ISSUER and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET)

def _oidc_config():
    cfg = cache.get('oidc_cfg', ttl=3600)
    if cfg:
        return cfg
    url = OIDC_ISSUER + '/.well-known/openid-configuration'
    cfg = json.loads(urllib.request.urlopen(url, timeout=6, context=_ssl_ctx).read())
    cache.set('oidc_cfg', cfg)
    return cfg

def _oidc_redirect_uri():
    return _hub_url() + '/auth/oidc/callback'

@app.route('/auth/oidc/login')
def oidc_login():
    if not oidc_enabled():
        return redirect(url_for('login_page'))
    try:
        cfg = _oidc_config()
    except Exception as e:
        return render_template('login.html', error=f'SSO nicht erreichbar: {e}'), 502
    state, nonce = _sec.token_urlsafe(24), _sec.token_urlsafe(24)
    session['oidc_state'], session['oidc_nonce'] = state, nonce
    q = urllib.parse.urlencode({'response_type': 'code', 'client_id': OIDC_CLIENT_ID,
                                'redirect_uri': _oidc_redirect_uri(), 'scope': 'openid email profile groups',
                                'state': state, 'nonce': nonce})
    return redirect(f"{cfg['authorization_endpoint']}?{q}")

@app.route('/auth/oidc/callback')
def oidc_callback():
    if not oidc_enabled():
        return redirect(url_for('login_page'))
    state = session.pop('oidc_state', None)
    if not state or request.args.get('state') != state or 'code' not in request.args:
        return render_template('login.html', error='SSO-Anmeldung abgebrochen oder abgelaufen'), 400
    try:
        cfg = _oidc_config()
        body = urllib.parse.urlencode({'grant_type': 'authorization_code', 'code': request.args['code'],
                                       'redirect_uri': _oidc_redirect_uri(), 'client_id': OIDC_CLIENT_ID,
                                       'client_secret': OIDC_CLIENT_SECRET}).encode()
        req = urllib.request.Request(cfg['token_endpoint'], data=body, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        tok = json.loads(urllib.request.urlopen(req, timeout=8, context=_ssl_ctx).read())
        # Identitaet ueber den userinfo-Endpunkt (TLS zum Issuer) statt lokaler JWT-Pruefung
        ureq = urllib.request.Request(cfg['userinfo_endpoint'])
        ureq.add_header('Authorization', f"Bearer {tok['access_token']}")
        info = json.loads(urllib.request.urlopen(ureq, timeout=8, context=_ssl_ctx).read())
    except Exception as e:
        _audit('?', 'login_fail', '', f'SSO-Fehler: {e}')
        return render_template('login.html', error='SSO-Anmeldung fehlgeschlagen'), 502
    u = (info.get('preferred_username') or info.get('email') or info.get('sub') or '').strip().lower()
    if not u:
        return render_template('login.html', error='SSO lieferte keinen Benutzernamen'), 400
    groups = info.get('groups') or []
    role = 'admin' if (OIDC_ADMIN_GROUP and OIDC_ADMIN_GROUP in groups) else None
    _users_ensure()
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute('SELECT role FROM users WHERE username=?', (u,)).fetchone()
    if row is None:
        role = role or (OIDC_DEFAULT_ROLE if OIDC_DEFAULT_ROLE in ('admin', 'viewer') else 'viewer')
        # Zufaelliges Passwort: SSO-Benutzer melden sich nur ueber SSO an
        conn.execute('INSERT INTO users (username,pw_hash,role,created_at) VALUES (?,?,?,?)',
                     (u, generate_password_hash(_sec.token_urlsafe(32)), role, time.strftime('%Y-%m-%dT%H:%M:%S')))
    else:
        if role and row[0] != role:
            conn.execute('UPDATE users SET role=? WHERE username=?', (role, u))
        role = role or row[0] or 'viewer'
    conn.commit(); conn.close()
    _login_finalize(u, role)
    session['sso'] = True
    return redirect(url_for('index'))

# ─── MCP (Model Context Protocol, Streamable HTTP, stateless) ─────────────
# Read-only Statusabfrage fuer Agenten. Auth: Authorization: Bearer <MCP_TOKEN>.

def _mcp_hosts():
    out = []
    for h in run_live_checks().get('hosts', []):
        m = h.get('metrics') or {}
        out.append({'ct_id': h.get('ct_id'), 'name': h.get('name'), 'ip': h.get('ip'),
                    'status': h.get('status'), 'category': h.get('category'),
                    'os': h.get('os_name'), 'cpu_pct': m.get('cpu'), 'ram_pct': m.get('ram'),
                    'services': h.get('services') or [],
                    'agent_online': bool(h.get('agent'))})
    return sorted(out, key=lambda x: (x['ct_id'] is None, x['ct_id'] or 0, x['name'] or ''))

def _mcp_containers():
    res = _px('/cluster/resources?type=vm') or {}
    out = []
    for r in res.get('data', []):
        out.append({'vmid': r.get('vmid'), 'name': r.get('name'), 'type': r.get('type'),
                    'node': r.get('node'), 'status': r.get('status'),
                    'cores': r.get('maxcpu'), 'mem_mb': int((r.get('maxmem') or 0) / 2**20),
                    'disk_gb': round((r.get('maxdisk') or 0) / 2**30, 1),
                    'cpu_pct': round(float(r.get('cpu') or 0) * 100, 1)})
    ips = discover_lxc_ips()
    for c in out:
        c['ip'] = (ips.get(str(c['vmid'])) or {}).get('ip')
    return sorted(out, key=lambda x: x['vmid'] or 0)

def _mcp_inventory_search(q):
    q = (q or '').strip().lower()
    if not q: return []
    _inv_ensure_table()
    conn = sqlite3.connect(AUDIT_DB)
    rows = conn.execute('SELECT host_key,packages_json FROM inventory').fetchall()
    conn.close()
    hits = []
    for hk, pj in rows:
        try: pkgs = json.loads(pj or '{}')
        except Exception: pkgs = {}
        hits += [{'host_key': hk, 'package': n, 'version': v} for n, v in pkgs.items() if q in n.lower()]
    return hits[:200]

def _mcp_find_host(ref):
    """Host per Schluessel, Name, IP oder CT-Nummer finden."""
    ref = str(ref or '').strip().lower()
    for h in (run_live_checks().get('hosts') or []):
        if ref in (str(h.get('key', '')).lower(), str(h.get('name', '')).lower(), str(h.get('ip', '')),
                   str(h.get('ct_id', ''))):
            return h
    return None

def _mcp_host_detail(a):
    h = _mcp_find_host(a.get('host'))
    if not h:
        return {'error': 'Host nicht gefunden (Name, IP oder CT-Nummer angeben)'}
    out = {k: h.get(k) for k in ('key', 'name', 'ip', 'ct_id', 'status', 'status_reason', 'os_name', 'metrics', 'services')}
    d = get_agent_docker(h['ip']) if h.get('ip') else None
    out['docker'] = (d or {}).get('containers') if d else 'kein Agent'
    return out

def _mcp_logs(a):
    if not LOKI_URL:
        return {'error': 'Loki ist nicht eingerichtet'}
    q = (a.get('logql') or '').strip()
    if not q:
        h = _mcp_find_host(a.get('host')) if a.get('host') else None
        sel = f'host="{h["ip"]}"' if h else 'job=~".+"'
        flt = (a.get('contains') or '').replace('"', '')
        q = '{' + sel + '}' + (f' |= "{flt}"' if flt else '')
    limit = max(1, min(int(a.get('limit') or 50), 300))
    minutes = max(1, min(int(a.get('minutes') or 60), 1440))
    params = urllib.parse.urlencode({'query': q, 'limit': limit, 'direction': 'backward',
                                     'start': str(int((time.time() - minutes * 60) * 1e9))})
    d = json.loads(urllib.request.urlopen(f'{LOKI_URL}/loki/api/v1/query_range?{params}', timeout=10).read())
    lines = []
    for st in d.get('data', {}).get('result', []):
        lab = st.get('stream', {})
        src = lab.get('hostname') or lab.get('host') or ''
        unit = lab.get('container') or lab.get('unit') or ''
        for ts, msg in st.get('values', []):
            lines.append({'ts': int(ts) // 10**9, 'src': f'{src}/{unit}', 'msg': msg[:400]})
    lines.sort(key=lambda x: x['ts'], reverse=True)
    return {'query': q, 'lines': lines[:limit]}

def _mcp_events(a):
    n = max(1, min(int(a.get('limit') or 50), 300))
    conn = sqlite3.connect(AUDIT_DB)
    rows = conn.execute('SELECT ts,user,action,host_key,detail FROM audit ORDER BY id DESC LIMIT ?', (n,)).fetchall()
    conn.close()
    return [{'ts': r[0], 'user': r[1], 'action': r[2], 'host': r[3], 'detail': r[4]} for r in rows]

def _mcp_network(a):
    if not (UNIFI_URL and UNIFI_USER):
        return {'error': 'UniFi ist nicht eingerichtet'}
    return get_unifi_data() or {'error': 'UniFi nicht erreichbar'}

# Nur lesend. Ist in agy ohne Rueckfrage freigegeben.
_MCP_TOOLS = {
    'list_containers': ('Alle Proxmox-Container/VMs mit VMID, Name, Status, IP und Ressourcen.',
                        {}, lambda a: _mcp_containers()),
    'infra_status':    ('Live-Status aller bekannten Hosts inkl. erreichbarer Dienste/Ports und Agent-Status.',
                        {}, lambda a: _mcp_hosts()),
    'host_detail':     ('Details zu einem Host: Status, Dienste, Docker-Container (via Agent).',
                        {'host': {'type': 'string', 'description': 'Name, IP oder CT-Nummer'}}, _mcp_host_detail),
    'list_agents':     ('Registrierte gl-agent-Instanzen mit letztem Heartbeat und Auslastung.',
                        {}, lambda a: _agents_list()),
    'active_alerts':   ('Aktuell aktive Alarme.', {}, lambda a: run_live_checks().get('alerts', [])),
    'query_logs':      ('Logs aus Loki. Entweder host (+ optional contains) oder eine eigene logql-Abfrage.',
                        {'host': {'type': 'string', 'description': 'Name, IP oder CT-Nummer (optional)'},
                         'contains': {'type': 'string', 'description': 'Textfilter (optional)'},
                         'logql': {'type': 'string', 'description': 'eigene LogQL-Abfrage (optional)'},
                         'minutes': {'type': 'integer', 'description': 'Zeitraum, Standard 60'},
                         'limit': {'type': 'integer', 'description': 'max. Zeilen, Standard 50'}}, _mcp_logs),
    'network_status':  ('UniFi: WAN, Geraete, Clients (Top 20 nach Traffic).', {}, _mcp_network),
    'recent_events':   ('Letzte Aktionen im RRM-Protokoll (wer hat was wann gemacht).',
                        {'limit': {'type': 'integer', 'description': 'Anzahl, Standard 50'}}, _mcp_events),
    'find_package':    ('Sucht ein installiertes Paket ueber alle inventarisierten Hosts.',
                        {'query': {'type': 'string', 'description': 'Paketname (Teilstring)'}},
                        lambda a: _mcp_inventory_search(a.get('query'))),
    'list_monitors':   ('Alle wiederkehrenden KI-Pruefungen mit letztem Ergebnis.', {}, lambda a: monitors_list()),
    'create_monitor':  ('Neue wiederkehrende KI-Pruefung anlegen (sichtbar im RRM unter KI-Ueberwachung). '
                        'Statt eigener Cron-Jobs IMMER dieses Werkzeug verwenden.',
                        {'name': {'type': 'string', 'description': 'kurzer Name'},
                         'prompt': {'type': 'string', 'description': 'Was geprueft werden soll'},
                         'interval_min': {'type': 'integer', 'description': 'Intervall in Minuten (min. 5)'}},
                        lambda a: {'ok': True, 'id': monitor_create(a.get('name'), a.get('prompt'), a.get('interval_min'), 'ki')}),
}

def _mcp_admin_docker(a):
    h = _mcp_find_host(a.get('host'))
    if not h:
        return {'ok': False, 'error': 'Host nicht gefunden'}
    act = a.get('action')
    if act == 'remove' and not a.get('confirm'):
        return {'ok': False, 'error': 'remove braucht confirm=true'}
    r = _agent_call(h['ip'], '/docker/action', {'name': a.get('name', ''), 'action': act, 'confirm': bool(a.get('confirm'))})
    _audit('ki', 'docker_' + str(act), h['key'], f"{a.get('name')}: {r.get('msg') or r.get('error')}")
    cache.bust()
    return r

def _mcp_admin_agent(a):
    h = _mcp_find_host(a.get('host'))
    if not h:
        return {'ok': False, 'error': 'Host nicht gefunden'}
    r = _agent_call(h['ip'], '/update', {'url': f'{DASHBOARD_URL_OR_LOCAL()}/agent/gl-agent.py'})
    _audit('ki', 'agent_update', h['key'], r.get('msg') or r.get('error') or '')
    return r

def DASHBOARD_URL_OR_LOCAL():
    return os.environ.get('DASHBOARD_URL', '').rstrip('/') or f"http://127.0.0.1:{os.environ.get('PORT', '8080')}"

def _mcp_admin_lxc(a):
    h = _mcp_find_host(a.get('host'))
    if not h or not h.get('ct_id'):
        return {'ok': False, 'error': 'Proxmox-Container nicht gefunden'}
    act = a.get('action')
    if act not in ('start', 'shutdown', 'reboot'):
        return {'ok': False, 'error': 'erlaubt: start, shutdown, reboot'}
    r = _px_write('POST', f"/nodes/{PROXMOX_NODE}/lxc/{h['ct_id']}/status/{act}", {})
    _audit('ki', f'lxc_{act}', h['key'], 'ok' if r.get('ok') else r.get('error', ''))
    return r

def _mcp_admin_backup(a):
    vmid = int(a.get('vmid') or 0)
    r = _px_write('POST', f'/nodes/{PROXMOX_NODE}/vzdump',
                  {'vmid': vmid, 'storage': a.get('storage') or 'local', 'mode': 'snapshot', 'compress': 'zstd'})
    _audit('ki', 'pve_backup', f'ct{vmid}', 'gestartet' if r.get('ok') else r.get('error', ''))
    return r

def _mcp_admin_onboot(a):
    vmid = int(a.get('vmid') or 0)
    r = _px_write('PUT', f'/nodes/{PROXMOX_NODE}/lxc/{vmid}/config', {'onboot': 1 if a.get('on') else 0})
    _audit('ki', 'pve_onboot', f'ct{vmid}', 'an' if a.get('on') else 'aus')
    return r

# Aendernd. Nur ueber /mcp/admin, in agy NICHT vorab freigegeben -> erst nach "Plan ausfuehren".
_MCP_ADMIN_TOOLS = {
    'docker_action':   ('Docker-Container verwalten: start, stop, restart, autostart_on, autostart_off, remove (confirm=true).',
                        {'host': {'type': 'string', 'description': 'Name, IP oder CT-Nummer'},
                         'name': {'type': 'string', 'description': 'Container-Name'},
                         'action': {'type': 'string', 'description': 'start|stop|restart|autostart_on|autostart_off|remove'},
                         'confirm': {'type': 'boolean', 'description': 'nur fuer remove'}}, _mcp_admin_docker),
    'agent_update':    ('Agent auf einem Host auf die aktuelle Version bringen.',
                        {'host': {'type': 'string', 'description': 'Name, IP oder CT-Nummer'}}, _mcp_admin_agent),
    'container_power': ('Proxmox-Container starten, herunterfahren oder neu starten.',
                        {'host': {'type': 'string', 'description': 'Name, IP oder CT-Nummer'},
                         'action': {'type': 'string', 'description': 'start|shutdown|reboot'}}, _mcp_admin_lxc),
    'backup_container':('Proxmox-Backup eines Containers starten.',
                        {'vmid': {'type': 'integer', 'description': 'CT-Nummer'},
                         'storage': {'type': 'string', 'description': 'Backup-Speicher, Standard local'}}, _mcp_admin_backup),
    'set_autostart':   ('Autostart eines Proxmox-Containers an/aus.',
                        {'vmid': {'type': 'integer', 'description': 'CT-Nummer'},
                         'on': {'type': 'boolean', 'description': 'true = an'}}, _mcp_admin_onboot),
}

@app.route('/mcp', methods=['POST', 'GET', 'DELETE'])
def mcp_endpoint():
    return _mcp_serve(_MCP_TOOLS, 'rrm')

@app.route('/mcp/admin', methods=['POST', 'GET', 'DELETE'])
def mcp_admin_endpoint():
    return _mcp_serve(_MCP_ADMIN_TOOLS, 'rrm-admin')

def _mcp_serve(tools, server_name):
    if not MCP_TOKEN or request.headers.get('Authorization', '') != f'Bearer {MCP_TOKEN}':
        return jsonify({'error': 'unauthorized'}), 401
    if request.method != 'POST':
        return ('', 405)
    msg = request.get_json(silent=True) or {}
    mid, method, params = msg.get('id'), msg.get('method', ''), msg.get('params') or {}
    if mid is None:                      # notification (z.B. notifications/initialized)
        return ('', 202)
    def ok(result): return jsonify({'jsonrpc': '2.0', 'id': mid, 'result': result})
    if method == 'initialize':
        return ok({'protocolVersion': params.get('protocolVersion', '2025-03-26'),
                   'capabilities': {'tools': {}},
                   'serverInfo': {'name': server_name, 'version': '1.1'}})
    if method == 'ping':
        return ok({})
    if method == 'tools/list':
        return ok({'tools': [{'name': n, 'description': d,
                              'inputSchema': {'type': 'object', 'properties': props,
                                              'required': [k for k in props if k in ('host', 'name', 'action', 'vmid', 'query', 'prompt')]}}
                             for n, (d, props, _) in tools.items()]})
    if method == 'tools/call':
        tool = tools.get(params.get('name'))
        if not tool:
            return jsonify({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32602, 'message': 'unknown tool'}})
        try:
            data = tool[2](params.get('arguments') or {})
            return ok({'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False, default=str)}]})
        except Exception as e:
            return ok({'content': [{'type': 'text', 'text': f'Fehler: {e}'}], 'isError': True})
    return jsonify({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'method not found'}})

if __name__ == '__main__':
    _init_audit()
    _init_crons()
    _init_host_meta()
    _init_metrics_tables()
    _init_agents()
    _init_settings()
    threading.Thread(target=_bg, daemon=True).start()
    threading.Thread(target=_cron_bg, daemon=True).start()
    threading.Thread(target=_nanoclaw_bg, daemon=True).start()
    threading.Thread(target=_metrics_bg, daemon=True).start()
    threading.Thread(target=_automations_bg, daemon=True).start()
    threading.Thread(target=_ai_bg, daemon=True).start()
    try:
        _users_ensure()
    except Exception as e:
        print(f'[users] seed: {e}')
    print('[Nanoclaw] Self-healing engine started')
    print('[Metrics] History storage started (60s interval)')
    if TELEGRAM_TOKEN:
        print(f'[Telegram] Configured — chat_id: {TELEGRAM_CHAT_ID[:6]}…')
    else:
        print('[Telegram] Not configured (set TELEGRAM_TOKEN + TELEGRAM_CHAT_ID)')
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)),
                 debug=False, allow_unsafe_werkzeug=True)
