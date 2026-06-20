#!/usr/bin/env python3
"""Goetschi Labs Dashboard v7 — Auto-Discovery Edition
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

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

app = Flask(__name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)
app.secret_key = os.environ.get('SECRET_KEY', 'goetschi-labs-v8-secret')
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

PROXMOX_HOST = os.environ.get('PROXMOX_HOST', '10.0.60.10')
PROXMOX_API  = f"https://{PROXMOX_HOST}:8006/api2/json"
PROXMOX_NODE = os.environ.get('PROXMOX_NODE', 'pve01')
PROXMOX_USER = os.environ.get('PROXMOX_USER', 'root@pam')
PROXMOX_PASS = os.environ.get('PROXMOX_PASS', '')
PROMETHEUS   = os.environ.get('PROMETHEUS_URL', 'http://10.0.60.110:9090')
LOKI_URL     = os.environ.get('LOKI_URL', 'http://10.0.60.110:3100')
DOKPLOY_URL  = os.environ.get('DOKPLOY_URL', 'http://10.0.60.121:3000')
DOKPLOY_KEY  = os.environ.get('DOKPLOY_API_KEY', '')
LITELLM_URL  = os.environ.get('LITELLM_URL', 'http://10.0.60.152:4000')
LITELLM_KEY  = os.environ.get('LITELLM_KEY', '')
COOLIFY_URL    = os.environ.get('COOLIFY_URL', 'http://10.0.60.139:8000')
COOLIFY_KEY    = os.environ.get('COOLIFY_API_KEY', '')
UNIFI_URL      = os.environ.get('UNIFI_URL', 'https://10.0.60.1')
UNIFI_USER     = os.environ.get('UNIFI_USER', 'hassio')
UNIFI_PASS     = os.environ.get('UNIFI_PASS', 'Riotstar_MICHEL_13')
UNIFI_SITE     = os.environ.get('UNIFI_SITE', 'default')
GL_AGENT_TOKEN = os.environ.get('GL_AGENT_TOKEN', 'gl-agent-goetschi-2026')
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
LXC_SSH_PASS   = os.environ.get('LXC_SSH_PASS', 'Louis_one_13')
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Per-host SSH overrides: key → (user, pass)
SSH_OVERRIDES = {
    'casaos': ('michel', LXC_SSH_PASS),
}
AUDIT_DB       = os.environ.get('AUDIT_DB', '/app/audit.db')

# Hermes agent API keys: env GL_HERMES_KEY_<NAME>=<token>
HERMES_AGENTS  = {v: k.replace('GL_HERMES_KEY_', '').lower()
                  for k, v in os.environ.items() if k.startswith('GL_HERMES_KEY_')}
# Default dev key
if not HERMES_AGENTS:
    HERMES_AGENTS['hermes-dev-key-2026'] = 'hermes-dev'
CACHE_TTL     = 5
DISCOVERY_TTL = 90

USERS = {
    'michel': generate_password_hash(os.environ.get('PASSWORD_MICHEL', 'line13')),
    'louis':  generate_password_hash(os.environ.get('PASSWORD_LOUIS',  'line13')),
}

SCAN_PORTS = [
    80, 81, 443, 1713, 2000, 3000, 3001, 3010, 3023, 3033, 3034,
    3100, 3389, 4000, 4001, 4010, 5000, 5001, 5002, 5003, 5004,
    5006, 5038, 5060, 5432, 5678, 5984, 6080, 6333, 6334, 6379,
    7878, 8000, 8001, 8002, 8006, 8080, 8086, 8088, 8096, 8123,
    8181, 8443, 8880, 8888, 8989, 9000, 9001, 9090, 9100, 9117,
    9443, 9696, 9998, 11434,
]

PORT_NAMES = {
    80:    ('HTTP',           True),
    443:   ('HTTPS',          True),
    1713:  ('Goetschi Web',   True),
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
    8123:  ('Home Assistant', True),
    8181:  ('Dashboard',      True),
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

# key: (name, ip, icon, category, ct_id, services[(port, svc_name, has_http, desc)])
STATIC_HOSTS = {
    'unifi':      ('UniFi Dream Machine',   '10.0.60.1',   '🌐', 'infra',   None,  [(443,   'UniFi Web UI',    True,  'Network Mgmt')]),
    'proxmox':    ('Proxmox VE',            '10.0.60.10',  '🖥️', 'infra',   None,  [(8006,  'Proxmox Web',     True,  'Hypervisor')]),
    'dokploy':    ('Dokploy',               '10.0.60.121', '🐳', 'infra',   100,   [
        (3000,  'Dokploy',       True,  'Docker Orchestration'),
        (8181,  'Dashboard',     True,  'Dieses Dashboard'),
        (9443,  'Portainer',     True,  'Docker UI'),
        (5678,  'n8n',           True,  'Automation'),
        (1713,  'Goetschi Web',  True,  'Website'),
        (3023,  'MCP Dokploy',   True,  'MCP Server'),
        (3033,  'Moto Poschung', True,  'Motorrad-Suche'),
        (8420,  'Signal News',   True,  'Signal-Bot'),
    ]),
    'paperless':  ('Paperless-NGX',         '10.0.40.30',  '📄', 'app',     103,   [(80,    'Paperless NGX',   True,  'Dokument-Mgmt')]),
    'pgvector':   ('PostgreSQL PGVector',   '10.0.60.141', '🗄️', 'infra',   105,   [(5432,  'PostgreSQL',      False, 'Vektor-DB')]),
    'mcphub':     ('MCPHub',                '10.0.60.170', '🔌', 'core',    107,   [
        (3000,  'MCPHub',        True,  'MCP Gateway'),
        (8002,  'Google MCP',    True,  'Gmail/Calendar'),
    ]),
    'influxdb':   ('InfluxDB',              '10.0.60.140', '📊', 'infra',   109,   [
        (8086,  'InfluxDB',      True,  'Zeitreihen-DB'),
        (8088,  'Chronograf',    True,  'Web UI'),
    ]),
    'monitoring': ('Monitoring Stack',      '10.0.60.110', '📈', 'infra',   110,   [
        (3000,  'Grafana',       True,  'Dashboards'),
        (3100,  'Loki',          True,  'Log-Aggregation'),
        (9090,  'Prometheus',    True,  'Metriken'),
    ]),
    'nova':       ('NOVA',                  '10.0.60.167', '🧠', 'agent',   112,   []),
    'litellm':    ('LiteLLM Dedicated',     '10.0.60.152', '⚡', 'ai',      116,   [(4000,  'LiteLLM',         True,  'LLM Gateway')]),
    'voice':      ('Voice Gateway',         '10.0.60.60',  '📞', 'voice',   117,   [
        (8000,  'Dograh API',    True,  'Voice Gateway'),
        (3010,  'Dograh UI',     True,  'Web Interface'),
        (8001,  'Nova Call API', True,  'Call API'),
        (8088,  'Asterisk HTTP', True,  'Asterisk Mgmt'),
        (8880,  'Uvicorn API',   True,  'Python API'),
        (6379,  'Redis',         False, 'Message Broker'),
        (5432,  'PostgreSQL',    False, 'Database'),
        (5060,  'SIP',           False, 'VoIP Trunk'),
        (5038,  'Asterisk AMI',  False, 'Manager Interface'),
    ]),
    'coolify':    ('Coolify',               '10.0.60.139', '🚀', 'infra',   118,   [
        (8000,  'Coolify',       True,  'PaaS'),
        (80,    'Traefik',       True,  'Proxy'),
        (9443,  'Portainer',     True,  'Docker UI'),
        (5006,  'Actual Budget', True,  'Budget'),
        (5984,  'CouchDB',       True,  'Obsidian Sync'),
        (3034,  'BesorgsDir',    True,  'WordPress'),
    ]),
    'magos':      ('Magos',                 '10.0.60.186', '🔮', 'ai',      401,   []),
    'orion':      ('Orion',                 '10.0.60.135', '✨', 'ai',      402,   []),
    'hermes':     ('Hermes',                '10.0.60.156', '🐍', 'agent',   108,   [
        (5002,  'Hermes API',    True,  'Python Agent'),
    ]),
    'mt5-bot4':   ('MT5 Bot 04',            '10.0.60.104', '💹', 'app',     504,   [
        (8080,  'MT5 Python API',True,  'Trading API'),
        (6080,  'noVNC Web',     True,  'Web VNC'),
        (3389,  'xRDP',          False, 'Remote Desktop'),
        (5901,  'x11VNC',        False, 'VNC Server'),
    ]),
    'minio':      ('MinIO Storage',         '10.0.60.106', '💾', 'infra',   505,   [
        (9000,  'MinIO API',     True,  'Object Storage'),
        (9001,  'MinIO Web',     True,  'Web UI'),
    ]),
    'qdrant':     ('Qdrant Vector DB',      '10.0.60.179', '🧬', 'ai',      506,   [
        (6333,  'Qdrant API',    True,  'Vector DB'),
        (6334,  'Qdrant gRPC',   False, 'gRPC'),
    ]),
    'smarthome':  ('Smart Home',            '10.0.60.111', '🏠', 'core',    None,  [(8123,  'Home Assistant',  False, 'Smarthome')]),
    'casaos':     ('CasaOS',               '10.0.60.201', '🏗️', 'app',     None,  [
        (80,    'CasaOS Web',    True,  'Home Server OS'),
        (10081, 'Nextcloud',     True,  'Cloud Storage'),
        (32400, 'Plex',          True,  'Media Server'),
        (7878,  'Radarr',        True,  'Film Manager'),
        (8989,  'Sonarr',        True,  'Serien Manager'),
        (9696,  'Prowlarr',      True,  'Indexer Manager'),
        (8082,  'qBittorrent',   True,  'Download Client'),
        (8191,  'FlareSolverr',  True,  'Cloudflare Bypass'),
    ]),
}

DEPENDENCIES = {
    'nova':       ['proxmox', 'monitoring', 'litellm'],
    'litellm':    [],
    'dokploy':    ['proxmox', 'unifi'],
    'monitoring': ['proxmox'],
    'voice':      ['litellm', 'dokploy'],
    'mcphub':     ['litellm'],
    'casaos':     ['unifi'],
    'unifi':      [],
    'proxmox':    ['unifi'],
    'hermes':     ['litellm'],
    'smarthome':  ['unifi'],
    'coolify':    ['proxmox', 'unifi'],
    'minio':      ['proxmox'],
    'qdrant':     ['proxmox'],
    'magos':      ['proxmox', 'litellm'],
    'orion':      ['proxmox', 'litellm'],
    'influxdb':   ['proxmox'],
    'pgvector':   ['proxmox'],
    'mt5-bot4':   ['proxmox'],
    'paperless':  ['proxmox'],
}

SERVICE_URLS = {
    'unifi':      {'UniFi Web UI': 'https://10.0.60.1:8443'},
    'proxmox':    {'Proxmox Web': 'https://10.0.60.10:8006'},
    'dokploy':    {'Dokploy': 'http://10.0.60.121:3000', 'Dashboard': 'http://10.0.60.121:8181',
                   'Portainer': 'https://10.0.60.121:9443',
                   'n8n': 'http://10.0.60.121:5678', 'Goetschi Web': 'http://10.0.60.121:1713',
                   'MCP Dokploy': 'http://10.0.60.121:3023',
                   'Moto Poschung': 'http://10.0.60.121:3033',
                   'Signal News': 'http://10.0.60.121:8420'},
    'mcphub':     {'MCPHub': 'http://10.0.60.170:3000', 'Google MCP': 'http://10.0.60.170:8002'},
    'influxdb':   {'InfluxDB': 'http://10.0.60.140:8086', 'Chronograf': 'http://10.0.60.140:8088'},
    'monitoring': {'Grafana': 'http://10.0.60.110:3000', 'Loki': 'http://10.0.60.110:3100', 'Prometheus': 'http://10.0.60.110:9090'},
    'nova':       {'Dashboard': 'http://10.0.60.167:8181'},
    'voice':      {'Dograh API': 'http://10.0.60.60:8000', 'Dograh UI': 'http://10.0.60.60:3010',
                   'Nova Call API': 'http://10.0.60.60:8001',
                   'Asterisk HTTP': 'http://10.0.60.60:8088',
                   'Uvicorn API': 'http://10.0.60.60:8880'},
    'hermes':     {'Hermes API': 'http://10.0.60.156:5002'},
    'mt5-bot4':   {'MT5 Python API': 'http://10.0.60.104:8080', 'noVNC Web': 'http://10.0.60.104:6080'},
    'coolify':    {'Coolify': 'http://10.0.60.139:8000', 'Traefik': 'http://10.0.60.139:80',
                   'Portainer': 'https://10.0.60.139:9443', 'Actual Budget': 'http://10.0.60.139:5006',
                   'CouchDB': 'http://10.0.60.139:5984', 'BesorgsDir': 'http://10.0.60.139:3034'},
    'minio':      {'MinIO API': 'http://10.0.60.106:9000', 'MinIO Web': 'http://10.0.60.106:9001'},
    'qdrant':     {'Qdrant API': 'http://10.0.60.179:6333'},
    'smarthome':  {'Home Assistant': 'http://10.0.60.111:8123'},
    'casaos':     {
        'CasaOS Web':   'http://10.0.60.201:80',
        'Nextcloud':    'http://10.0.60.201:10081',
        'Plex':         'http://10.0.60.201:32400/web',
        'Radarr':       'http://10.0.60.201:7878',
        'Sonarr':       'http://10.0.60.201:8989',
        'Prowlarr':     'http://10.0.60.201:9696',
        'qBittorrent':  'http://10.0.60.201:8082',
        'FlareSolverr': 'http://10.0.60.201:8191',
    },
    'litellm':    {'LiteLLM': 'http://10.0.60.152:4000'},
}

EXTERNAL_LINKS = [
    {'name': 'Jira',       'url': 'https://goetschi.atlassian.net/jira', 'icon': '🎯', 'desc': 'Issue Tracking'},
    {'name': 'Confluence', 'url': 'https://goetschi.atlassian.net/wiki', 'icon': '📝', 'desc': 'Wiki'},
    {'name': 'Cloudflare', 'url': 'https://dash.cloudflare.com',         'icon': '☁️', 'desc': 'DNS/CDN'},
]

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

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
    _tg_send(f'🚨 *Goetschi Labs*\n*Host:* {host_name}\n*Problem:* {msg}\n_{time.strftime("%H:%M:%S")}_')

def _tg_check_alerts(hosts_data):
    for h in hosts_data:
        key  = h['key']
        name = h['name']
        ag   = h.get('agent') or {}
        m    = h.get('metrics') or {}
        if h['status'] == 'offline':
            _tg_alert(f'{key}:offline', f'{name} ({h["ip"]}) ist offline 🔴')
        cpu = (m.get('cpu') if m.get('cpu') is not None else ag.get('cpu_pct', 0)) or 0
        dsk = (m.get('disk_pct') if m.get('disk_pct') is not None else (ag.get('disk') or {}).get('pct', 0)) or 0
        if cpu > 90: _tg_alert(f'{key}:cpu', f'{name}: CPU {cpu:.0f}% ⚡')
        if dsk > 88: _tg_alert(f'{key}:disk', f'{name}: Disk {dsk}% 💾')
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
        conn.commit(); conn.close()
    except Exception as e:
        print(f'[cron] init failed: {e}')

def _run_cron_job(cron_id):
    conn = sqlite3.connect(AUDIT_DB)
    row = conn.execute('SELECT * FROM crons WHERE id=?', (cron_id,)).fetchone()
    conn.close()
    if not row:
        return
    cols = ['id','name','host_key','command','interval_min','enabled','created_at','last_run','last_ok','last_result','next_run']
    c = dict(zip(cols, row))

    h = STATIC_HOSTS.get(c['host_key'])
    ip = h[1] if h else None
    result = ''
    ok = False
    try:
        if ip:
            ssh_user, ssh_pass = SSH_OVERRIDES.get(c['host_key'], (LXC_SSH_USER, LXC_SSH_PASS))
            ssh = _paramiko.SSHClient()
            ssh.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
            ssh.connect(ip, port=22, username=ssh_user, password=ssh_pass,
                        timeout=10, look_for_keys=False, allow_agent=False)
            _, o, e = ssh.exec_command(c['command'], timeout=120)
            out = o.read().decode('utf-8','replace').strip()
            err = e.read().decode('utf-8','replace').strip()
            ssh.close()
            result = (out + ('\n' + err if err else ''))[:1000]
            ok = True
        else:
            result = f'Error: unknown host {c["host_key"]}'
    except Exception as ex:
        result = str(ex)[:500]

    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    nxt = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() + c['interval_min'] * 60))
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('UPDATE crons SET last_run=?,last_ok=?,last_result=?,next_run=? WHERE id=?',
                 (now, int(ok), result, nxt, cron_id))
    conn.commit(); conn.close()
    _audit('scheduler', 'cron_run', c['host_key'], f"{c['name']}: {'OK' if ok else 'FAIL'}")

def _cron_bg():
    import math
    while True:
        try:
            now_str = time.strftime('%Y-%m-%dT%H:%M:%S')
            conn = sqlite3.connect(AUDIT_DB)
            due = conn.execute(
                "SELECT id FROM crons WHERE enabled=1 AND (next_run IS NULL OR next_run <= ?)",
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

def _unifi_login():
    global _unifi_cookie, _unifi_csrf, _unifi_expiry
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
        print(f'[UniFi] login failed: {e}')
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

def _px(path):
    t = _px_login()
    if not t: return None
    try:
        req = urllib.request.Request(f"{PROXMOX_API}{path}")
        req.add_header('Cookie', f'PVEAuthCookie={t}')
        return json.loads(urllib.request.urlopen(req, timeout=5, context=_ssl_ctx).read())
    except Exception:
        return None

# ─── AUTO-DISCOVERY ───────────────────────────

def discover_lxc_ips():
    cached = cache.get('lxc_ips', ttl=DISCOVERY_TTL)
    if cached is not None:
        return cached
    resp = _px(f'/nodes/{PROXMOX_NODE}/lxc')
    if not resp or 'data' not in resp:
        return {}
    result = {}
    for lxc in resp['data']:
        vmid   = str(lxc.get('vmid', ''))
        name   = lxc.get('name', f'ct{vmid}')
        status = lxc.get('status', 'unknown')
        ip = None
        if status == 'running':
            ifaces = _px(f'/nodes/{PROXMOX_NODE}/lxc/{vmid}/interfaces')
            if ifaces and 'data' in ifaces:
                for iface in ifaces['data']:
                    if iface.get('name', '') == 'lo':
                        continue
                    inet = iface.get('inet', '')
                    if inet and '/' in inet:
                        candidate = inet.split('/')[0]
                        if candidate and not candidate.startswith('127.'):
                            ip = candidate
                            break
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

def run_discovery():
    cached = cache.get('discovery', ttl=DISCOVERY_TTL)
    if cached is not None:
        return cached

    lxc_ips    = discover_lxc_ips()
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
        if not open_ports:
            continue

        svcs = []
        for port in open_ports:
            nm, has_http = PORT_NAMES.get(port, (f':{port}', True))
            svcs.append((port, nm, has_http, 'auto-discovered'))

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
# nutzerseitige Dienste (Michel will den Grafana-Link!) → NICHT skippen.
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
        for r in d['data']:
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
    'echo "###PKGS"; dpkg-query -W 2>/dev/null'
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
    vmid = _host_vmid(host_key)
    if not vmid:
        return {'ok': False, 'error': 'Kein LXC / keine VMID'}
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
        AGENT_HOSTS = {'casaos', 'smarthome'}
        for key, (name, ip, icon, cat, ct_id, services) in effective.items():
            futures[pool.submit(_ping, ip)] = f'ping:{key}'
            if ct_id or key in AGENT_HOSTS:
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
        has_agent = bool(ct_id or key in AGENT_HOSTS)
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
            'parent':  'proxmox' if h['key'] not in ('unifi', '_internet') else 'unifi',
        }
    topology['_internet'] = {'label': '🌍 Internet', 'ip': None, 'status': 'online', 'parent': None}
    topology['unifi']['parent']   = '_internet'
    topology['proxmox']['parent'] = 'unifi'

    # ── Alert generation ──────────────────────────
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

        if cpu > 90:
            active_alerts.append({'severity': 'warn', 'key': key, 'host': name, 'ip': ip,
                                   'msg': f'CPU {cpu:.0f}%', 'ts': int(time.time())})
        if mem > 90:
            active_alerts.append({'severity': 'warn', 'key': key, 'host': name, 'ip': ip,
                                   'msg': f'RAM {mem:.0f}%', 'ts': int(time.time())})
        if dsk > 85:
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
        if h['ssl_min_days'] is not None and h['ssl_min_days'] < 30:
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
    error = None
    if request.method == 'POST':
        u = request.form.get('username', '').strip().lower()
        p = request.form.get('password', '')
        if u in USERS and check_password_hash(USERS[u], p):
            session.clear()
            session['authenticated'] = True
            session['username'] = u
            session.permanent = True
            return redirect(url_for('index'))
        error = 'Ungültige Zugangsdaten'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/')
@login_required
def index():
    # New React SPA (Vite build) lives in static/spa. Falls back to the legacy
    # template if the build isn't present (e.g. local dev without a frontend build).
    spa = os.path.join(app.static_folder, 'spa', 'index.html')
    if os.path.exists(spa):
        return send_from_directory(os.path.join(app.static_folder, 'spa'), 'index.html')
    return render_template('index.html', username=session.get('username'))

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
    RESTARTABLE = {'moto-poschung': 'moto-test', 'dashboard': 'goetschi-dashboard'}
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
@login_required
def api_container_action(host_key, action):
    name = (request.json or {}).get('name', '')
    _audit(request.remote_addr, f'container_{action}', host_key, name)
    return jsonify(container_action(host_key, name, action))

@app.route('/api/container/bulk', methods=['POST'])
@login_required
def api_container_bulk():
    d = request.json or {}
    action = d.get('action', '')
    targets = d.get('targets', [])[:50]
    _audit(request.remote_addr, f'bulk_{action}', '', f'{len(targets)} targets')
    results = []
    for t in targets:
        r = container_action(t.get('host', ''), t.get('name', ''), action)
        results.append({'host': t.get('host'), 'name': t.get('name'), **r})
    ok_n = sum(1 for r in results if r.get('ok'))
    return jsonify({'ok': True, 'done': ok_n, 'total': len(results), 'results': results})

# ─── AI ANALYSIS (LiteLLM) ─────────────────────
def _llm_chat(messages, model='gemini-flash', max_tokens=2000, temperature=0.3):
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
    if not question:
        return jsonify({'ok': False, 'error': 'Frage fehlt'})
    if not LITELLM_KEY:
        return jsonify({'ok': False, 'error': 'LITELLM_KEY nicht gesetzt'})
    ctx = _build_ai_context(host_key)
    messages = [
        {'role': 'system', 'content':
            'Du bist der KI-Analyst der Goetschi-Control-Infrastruktur (Proxmox, LXC, Docker, '
            'Prometheus, Loki, UniFi). Antworte auf Deutsch, knapp und konkret. Stütze dich nur '
            'auf die gegebenen Daten; wenn etwas fehlt, sage es. Gib bei Problemen mögliche '
            'Ursachen und konkrete nächste Schritte.'},
        {'role': 'user', 'content': f'INFRASTRUKTUR-KONTEXT:\n{ctx}\n\nFRAGE: {question}'},
    ]
    _audit(request.remote_addr, 'ai_analyze', host_key or '', question[:80])
    try:
        answer = _llm_chat(messages) or '(keine Antwort vom Modell — evtl. Token-Limit)'
        return jsonify({'ok': True, 'answer': answer, 'model': 'gemini-flash', 'host_key': host_key})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/lxc/<host_key>/<action>', methods=['POST'])
@login_required
def api_lxc_action(host_key, action):
    _audit(request.remote_addr, f'lxc_{action}', host_key, '')
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
@login_required
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
        if h[4] or k in {'casaos', 'smarthome'}
    ]
    return jsonify({
        'agent_token':          GL_AGENT_TOKEN,
        'agent_port':           AGENT_PORT,
        'hermes_agents':        hermes,
        'agent_hosts':          agent_hosts,
        'dashboard_url':        os.environ.get('DASHBOARD_URL', 'http://10.0.60.121:8181'),
        'telegram_configured':  bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
        'telegram_chat_id':     TELEGRAM_CHAT_ID[:6] + '…' if TELEGRAM_CHAT_ID else '',
    })

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
    _audit(request.remote_addr, 'inv_scan', host_key, '')
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
    _audit(request.remote_addr, 'inv_scan_all', '', f'{len(keys)} hosts')
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
    _audit(request.remote_addr, 'nc_diagnose', host_key, f'{source}:{container_name}')
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
_LL_FALLBACK_MODELS = ['gemini-flash', 'deepseek-v4-flash', 'gemini-2.0-flash-lite', 'openrouter-auto']

def _ll_read_models():
    now = time.time()
    if now - _ll_models_cache['ts'] < 3600 and _ll_models_cache['models']:
        return _ll_models_cache['models']
    try:
        c = _paramiko.SSHClient()
        c.set_missing_host_key_policy(_paramiko.AutoAddPolicy())
        c.connect(PROXMOX_HOST, port=22, username='root', password=PROXMOX_PASS,
                  timeout=8, look_for_keys=False, allow_agent=False)
        script = "import yaml,json;d=yaml.safe_load(open('/etc/litellm/config.yaml'));print(json.dumps(list(dict.fromkeys(x['model_name'] for x in d.get('model_list',[])))))"
        _, out, _ = c.exec_command(f'pct exec 116 -- python3 -c "{script}"', timeout=12)
        models = json.loads(out.read().decode().strip())
        c.close()
        _ll_models_cache['models'] = models
        _ll_models_cache['ts'] = now
        return models
    except Exception as e:
        print(f'[LiteLLM] model parse: {e}')
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
@login_required
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
    _audit(request.remote_addr, 'host_meta', host_key, f"cat={d.get('category')}")
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
@login_required
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
        _audit(request.remote_addr, 'token_create', name, token[:12]+'…')
        return jsonify({'ok': True, 'id': tid, 'name': name, 'token': token})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

@app.route('/api/tokens/<token_id>', methods=['DELETE'])
@login_required
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

    docker_data = get_agent_docker('10.0.60.121')
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
    ok = _tg_send('🟢 *Goetschi Labs Dashboard*\nTest-Nachricht — alles funktioniert! ✅')
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
    rows = conn.execute('SELECT id,name,host_key,command,interval_min,enabled,created_at,last_run,last_ok,last_result,next_run FROM crons ORDER BY created_at DESC').fetchall()
    conn.close()
    cols = ['id','name','host_key','command','interval_min','enabled','created_at','last_run','last_ok','last_result','next_run']
    return jsonify([dict(zip(cols, r)) for r in rows])

@app.route('/api/crons', methods=['POST'])
@login_required
def api_crons_create():
    d = request.json or {}
    if not d.get('command') or not d.get('host_key'):
        return jsonify({'error': 'host_key and command required'}), 400
    cid = str(_uuid.uuid4())[:8]
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('INSERT INTO crons (id,name,host_key,command,interval_min,enabled,created_at,next_run) VALUES (?,?,?,?,?,1,?,?)',
                 (cid, d.get('name','unnamed'), d['host_key'], d['command'],
                  int(d.get('interval_min', 60)), now, now))
    conn.commit(); conn.close()
    _audit(session.get('username','?'), 'cron_create', d['host_key'], d.get('name',''))
    return jsonify({'id': cid, 'ok': True})

@app.route('/api/crons/<cron_id>', methods=['PATCH'])
@login_required
def api_crons_update(cron_id):
    d = request.json or {}
    conn = sqlite3.connect(AUDIT_DB)
    if 'enabled' in d:
        conn.execute('UPDATE crons SET enabled=? WHERE id=?', (int(d['enabled']), cron_id))
    if 'interval_min' in d:
        conn.execute('UPDATE crons SET interval_min=? WHERE id=?', (int(d['interval_min']), cron_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/crons/<cron_id>', methods=['DELETE'])
@login_required
def api_crons_delete(cron_id):
    conn = sqlite3.connect(AUDIT_DB)
    conn.execute('DELETE FROM crons WHERE id=?', (cron_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/crons/<cron_id>/run', methods=['POST'])
@login_required
def api_crons_run(cron_id):
    threading.Thread(target=_run_cron_job, args=(cron_id,), daemon=True).start()
    return jsonify({'ok': True, 'msg': 'Triggered'})

if __name__ == '__main__':
    _init_audit()
    _init_crons()
    _init_host_meta()
    _init_metrics_tables()
    _init_agents()
    threading.Thread(target=_bg, daemon=True).start()
    threading.Thread(target=_cron_bg, daemon=True).start()
    threading.Thread(target=_nanoclaw_bg, daemon=True).start()
    threading.Thread(target=_metrics_bg, daemon=True).start()
    print('[Nanoclaw] Self-healing engine started')
    print('[Metrics] History storage started (60s interval)')
    if TELEGRAM_TOKEN:
        print(f'[Telegram] Configured — chat_id: {TELEGRAM_CHAT_ID[:6]}…')
    else:
        print('[Telegram] Not configured (set TELEGRAM_TOKEN + TELEGRAM_CHAT_ID)')
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)),
                 debug=False, allow_unsafe_werkzeug=True)
