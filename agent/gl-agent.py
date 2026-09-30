#!/usr/bin/env python3
"""RRM Agent — host monitoring + optional container self-healing.
Stdlib only — no pip installs needed. Port 9998, auth via Bearer token.

Install (empfohlen): im Dashboard unter "Verbinden" den Ein-Zeilen-Befehl kopieren.
Manuell:
  cp gl-agent.py /opt/gl-agent.py
  chmod +x /opt/gl-agent.py

Systemd (paste to /etc/systemd/system/gl-agent.service):
  [Unit]
  Description=RRM Agent
  After=network.target

  [Service]
  ExecStart=/usr/bin/python3 /opt/gl-agent.py
  Restart=always
  RestartSec=5
  EnvironmentFile=/etc/gl-agent.env

  [Install]
  WantedBy=multi-user.target

  /etc/gl-agent.env (chmod 600, root:root):
  GL_AGENT_TOKEN=<unique-uuid-per-lxc>
  GL_AGENT_ALLOWED_IPS=<hub-ip>
  GL_HUB_URL=http://<hub-ip>:8181

  Then: systemctl daemon-reload && systemctl enable --now gl-agent
"""
import http.server, json, os, subprocess, socket, time, re, threading
from urllib.parse import urlparse, parse_qs

AGENT_VERSION     = '3.1'
AGENT_PATH        = os.path.abspath(__file__)
TOKEN             = os.environ.get('GL_AGENT_TOKEN', '')
PORT              = int(os.environ.get('GL_AGENT_PORT', 9998))
BIND_IP           = os.environ.get('GL_AGENT_BIND_IP', '0.0.0.0')
ALLOWED_IPS       = {x.strip() for x in os.environ.get('GL_AGENT_ALLOWED_IPS', '').split(',') if x.strip()}
# Nanoclaw-Selbstheilung jetzt per Default AUS (Default '0') — nur explizit aktivierbar.
NC_ENABLED        = os.environ.get('NC_ENABLED', '0') not in ('0', 'false', 'no')
# Self-Registration beim Hub
GL_HUB_URL        = os.environ.get('GL_HUB_URL', '').rstrip('/')
GL_REGISTER       = os.environ.get('GL_REGISTER', '1') not in ('0', 'false', 'no')
GL_REGISTER_INT   = int(os.environ.get('GL_REGISTER_INTERVAL', '60'))
NC_DISK_THRESHOLD = int(os.environ.get('NC_DISK_THRESHOLD', '88'))
START_TS          = time.time()

import urllib.request as _ulib

# Rate limiting for /restart: max 10 calls per minute per source IP
_restart_calls: dict = {}
_restart_lock  = threading.Lock()

def _check_restart_rate(client_ip: str, limit: int = 10, window: int = 60) -> bool:
    now = time.time()
    with _restart_lock:
        times = [t for t in _restart_calls.get(client_ip, []) if now - t < window]
        if len(times) >= limit:
            return False
        times.append(now)
        _restart_calls[client_ip] = times
        return True

def _primary_ip():
    """Echte LAN-IP (egress-Interface), nicht der 127.0.1.1-Loopback-Alias."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.0.2.1', 9))   # sendet nichts; waehlt nur das Egress-Interface
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return '?'

def _run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ''

def _run2(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return '', str(e)

# ══════════════════════════════════════════════════════
# MONITORING
# ══════════════════════════════════════════════════════

def get_status():
    uptime = 0
    try:
        uptime = float(open('/proc/uptime').read().split()[0])
    except Exception:
        pass

    cpu_pct = 0
    try:
        l1 = open('/proc/stat').readline().split()
        time.sleep(0.15)
        l2 = open('/proc/stat').readline().split()
        idle1  = int(l1[4]) + int(l1[5])
        idle2  = int(l2[4]) + int(l2[5])
        total1 = sum(int(x) for x in l1[1:])
        total2 = sum(int(x) for x in l2[1:])
        dt = total2 - total1
        di = idle2 - idle1
        cpu_pct = round((1 - di / dt) * 100, 1) if dt > 0 else 0
    except Exception:
        pass

    mem_pct = mem_used_gb = mem_total_gb = 0
    try:
        mem = {}
        for line in open('/proc/meminfo'):
            k, v = line.split(':', 1)
            mem[k.strip()] = int(v.strip().split()[0]) * 1024
        mt = mem.get('MemTotal', 1)
        ma = mem.get('MemAvailable', 0)
        mem_pct      = round((1 - ma / mt) * 100, 1)
        mem_used_gb  = round((mt - ma) / (1024**3), 2)
        mem_total_gb = round(mt / (1024**3), 2)
    except Exception:
        pass

    disk = {}
    try:
        out = _run("df -B1 / --output=size,used,avail,pcent")
        parts = out.splitlines()[1].split()
        disk = {
            'total_gb': round(int(parts[0]) / (1024**3), 1),
            'used_gb':  round(int(parts[1]) / (1024**3), 1),
            'avail_gb': round(int(parts[2]) / (1024**3), 1),
            'pct':      int(parts[3].rstrip('%')),
        }
    except Exception:
        pass

    hostname = socket.gethostname()
    ip = _primary_ip()

    net = {}
    try:
        for line in open('/proc/net/dev').readlines()[2:]:
            parts = line.split()
            iface = parts[0].rstrip(':')
            if iface == 'lo': continue
            net[iface] = {'rx_bytes': int(parts[1]), 'tx_bytes': int(parts[9])}
    except Exception:
        pass

    load = [0, 0, 0]
    ncpu = 1
    try:
        load = [float(x) for x in open('/proc/loadavg').read().split()[:3]]
        ncpu = os.cpu_count() or 1
    except Exception:
        pass

    # listening TCP ports (for richer service discovery)
    ports = []
    try:
        out = _run("ss -tlnH 2>/dev/null || netstat -tlnp 2>/dev/null", timeout=4)
        seen = set()
        for line in out.splitlines():
            m = re.search(r':(\d+)\s', line)
            if m:
                p = int(m.group(1))
                if p not in seen and p < 65536:
                    seen.add(p); ports.append(p)
        ports = sorted(ports)
    except Exception:
        pass

    return {
        'hostname':       hostname,
        'ip':             ip,
        'agent_version':  AGENT_VERSION,
        'uptime_h':       round(uptime / 3600, 2),
        'cpu_pct':        cpu_pct,
        'cpu_cores':      ncpu,
        'load':           [round(x, 2) for x in load],
        'mem_pct':        mem_pct,
        'mem_used_gb':    mem_used_gb,
        'mem_total_gb':   mem_total_gb,
        'disk':           disk,
        'net':            net,
        'listening_ports': ports,
        'docker_ok':      _docker_available(),
        'os':             _run('uname -r')[:60],
        'ts':             int(time.time()),
        'nanoclaw':       NC_ENABLED,
    }

def get_procs():
    out = _run("ps aux --sort=-%cpu")
    procs = []
    for line in out.splitlines()[1:11]:
        p = line.split(None, 10)
        if len(p) >= 11:
            procs.append({'user': p[0], 'pid': p[1], 'cpu': p[2], 'mem': p[3], 'cmd': p[10][:80]})
    return procs

_docker_cache    = {'containers': [], 'ts': 0}
_systemd_cache   = {'svcs': {}, 'ts': 0}
_CACHE_TTL       = 25  # seconds

def _refresh_docker():
    containers = []
    out = _run('docker ps -a --format "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}"', timeout=6)
    for line in out.splitlines():
        if '|' not in line:
            continue
        p = line.split('|', 4)
        if len(p) >= 4:
            containers.append({
                'id':     p[0][:12],
                'name':   p[1],
                'image':  p[2],
                'status': p[3],
                'ports':  p[4] if len(p) > 4 else '',
                'source': 'docker',
            })
    _docker_cache['containers'] = containers
    _docker_cache['ts'] = time.time()
    return containers

def _refresh_systemd():
    svcs = get_systemd_services()
    _systemd_cache['svcs'] = svcs
    _systemd_cache['ts'] = time.time()
    return svcs

def get_docker():
    now = time.time()
    if now - _docker_cache['ts'] > _CACHE_TTL:
        _refresh_docker()
    containers = list(_docker_cache['containers'])

    # Append cached systemd services
    if now - _systemd_cache['ts'] > _CACHE_TTL:
        _refresh_systemd()
    for unit, info in _systemd_cache['svcs'].items():
        sub = info['sub']
        status_str = f"{'Up' if sub == 'running' else sub} ({info['active']})"
        containers.append({
            'id': '', 'name': unit, 'image': info['desc'][:50],
            'status': status_str, 'ports': '', 'source': 'systemd',
        })
    return containers

def get_logs(n=40):
    cmd = (f'journalctl -n {n} --no-pager -o short-iso --no-hostname 2>/dev/null '
           f'|| tail -n {n} /var/log/syslog 2>/dev/null || echo "no logs available"')
    out = _run(cmd, timeout=5)
    lines = []
    for line in out.splitlines()[-n:]:
        level = 'info'
        low = line.lower()
        if any(x in low for x in ('error', 'crit', 'emerg', 'fail')):
            level = 'error'
        elif 'warn' in low:
            level = 'warn'
        lines.append({'msg': line[:200], 'level': level})
    return lines

def restart_service(name):
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', name):
        return {'ok': False, 'error': 'Invalid name'}
    r1 = subprocess.run(['docker', 'restart', name], capture_output=True, text=True, timeout=20)
    if r1.returncode == 0:
        return {'ok': True, 'msg': f'docker restart {name}'}
    r2 = subprocess.run(['systemctl', 'restart', name], capture_output=True, text=True, timeout=20)
    if r2.returncode == 0:
        return {'ok': True, 'msg': f'systemctl restart {name}'}
    return {'ok': False, 'error': (r1.stderr or r2.stderr).strip()[:200]}

# ══════════════════════════════════════════════════════
# NANOCLAW — Local Self-Healing Engine
# ══════════════════════════════════════════════════════

_nc_events    = []   # ring buffer max 200
_nc_cooldowns = {}   # { key: last_ts }
_nc_prev_ct   = {}   # { container_name: was_up }
_nc_prev_svc  = {}   # { unit_name: state }   for systemd watchdog
_nc_lock      = threading.Lock()

_NC_DOCKER_SKIP = {
    'promtail', 'node-exporter', 'loki', 'prometheus', 'grafana',
    'dokploy-postgres', 'dokploy-redis', 'dokploy-traefik', 'portainer',
}

# Systemd units to never touch (infra/OS)
_NC_SVC_SKIP_PREFIX = (
    'systemd-', 'getty@', 'serial-getty@', 'autovt@', 'user@', 'session-',
)
_NC_SVC_SKIP_EXACT = {
    'ssh', 'sshd', 'cron', 'rsyslog', 'syslog', 'dbus', 'networking',
    'network', 'NetworkManager', 'ntp', 'chronyd', 'chrony', 'ntpd',
    'timesyncd', 'ufw', 'iptables', 'nftables', 'apparmor', 'snapd',
    'multipathd', 'lvm2-monitor', 'mdmonitor', 'acpid', 'ModemManager',
    'keyboard-setup', 'console-setup', 'cloud-init', 'cloud-config',
    'cloud-final', 'open-vm-tools', 'qemu-guest-agent', 'fstrim',
    'apt-daily', 'apt-daily-upgrade', 'motd-news', 'unattended-upgrades',
    'gl-agent',          # never restart yourself
    'node-exporter', 'promtail', 'loki', 'prometheus', 'grafana',
    'wazuh-agent', 'wazuh-agentd', 'wazuh-logcollector', 'wazuh-modulesd',
    'smbd', 'nmbd', 'winbind',   # samba — restart would break shares
    'apache2', 'nginx',           # handled separately or intentionally stopped
}

_NC_DIAG = [
    (r'out of memory|oom.kill|killed process',    'OOM Kill',           'RAM-Limit erhöhen oder Memory-Leak prüfen'),
    (r'permission denied',                         'Permission Denied',  'Volume-Mounts oder User-ID prüfen'),
    (r'address already in use|bind.*failed',       'Port belegt',        'Port-Konflikt: anderen Prozess beenden'),
    (r'no space left on device',                   'Disk voll',          'Disk-Cleanup läuft automatisch'),
    (r'cannot connect|connection refused',         'Abhängigkeit fehlt', 'Service-Startrekhenfolge oder Netzwerk prüfen'),
    (r'exec format error',                         'Arch-Mismatch',      'Image für falsche CPU-Architektur gebaut'),
    (r'exit code[: ]+[1-9]|exited with code [1-9]','Exit Error',        'Env-Vars oder Konfiguration prüfen'),
    (r'certificate.*expired|ssl.*handshake',       'TLS-Fehler',         'Zertifikat erneuern'),
    (r'segfault|segmentation fault',               'Segfault',           'Bug im Prozess — Core-Dump prüfen'),
    (r'python.*traceback|exception.*traceback',    'Python-Exception',   'App-Logs auf Traceback prüfen'),
]

def _nc_cooldown_ok(key, seconds):
    with _nc_lock:
        if time.time() - _nc_cooldowns.get(key, 0) < seconds:
            return False
        _nc_cooldowns[key] = time.time()
        return True

def _nc_emit(action, detail, result, severity='info'):
    ev = {
        'ts':       int(time.time()),
        'ts_str':   time.strftime('%Y-%m-%dT%H:%M:%S'),
        'host':     socket.gethostname(),
        'action':   action,
        'detail':   detail,
        'result':   result,
        'severity': severity,
    }
    with _nc_lock:
        _nc_events.append(ev)
        if len(_nc_events) > 200:
            _nc_events.pop(0)
    print(f'[Nanoclaw] {severity.upper()} {action}: {detail} → {result[:80]}')

def _nc_diag_logs(source, name):
    """Fetch and pattern-match logs for docker container or systemd unit."""
    if source == 'docker':
        out, err = _run2(f'docker logs --tail=80 "{name}" 2>&1', timeout=10)
        logs = (out + err)
    else:
        logs = _run(f'journalctl -u "{name}" -n 60 --no-pager 2>/dev/null', timeout=8)
        err  = ''
    combined = logs.lower()
    for pattern, label, advice in _NC_DIAG:
        if re.search(pattern, combined):
            return {'label': label, 'advice': advice, 'logs': logs[-1200:]}
    return {'label': 'Unbekannt', 'advice': 'Keine Mustererkennung. Logs manuell prüfen.', 'logs': logs[-1200:]}

# Keep old name for HTTP handler compatibility
def nc_diagnose(container_name):
    return _nc_diag_logs('docker', container_name)

def _docker_available():
    out = _run('docker info --format "{{.ServerVersion}}" 2>/dev/null', timeout=4)
    return bool(out and out.strip())

def get_systemd_services():
    """Return dict of {unit: {active, sub, description}} for non-infra services."""
    out = _run(
        'systemctl list-units --type=service --no-pager --no-legend --all 2>/dev/null',
        timeout=8)
    svcs = {}
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit = parts[0]
        if unit.endswith('.service'):
            unit = unit[:-8]
        active = parts[2]   # active / inactive / failed / activating
        sub    = parts[3]   # running / dead / failed / exited / start
        desc   = parts[4].strip() if len(parts) > 4 else unit

        # Skip infra
        if any(unit.startswith(p) for p in _NC_SVC_SKIP_PREFIX):
            continue
        if unit in _NC_SVC_SKIP_EXACT:
            continue
        if unit.startswith('@'):
            continue

        svcs[unit] = {'active': active, 'sub': sub, 'desc': desc}
    return svcs

def _nc_tick():
    global _nc_prev_ct, _nc_prev_svc

    # ── Rule 1: Disk cleanup ──────────────────────────────
    try:
        out = _run("df -B1 / --output=pcent")
        pct = int(out.splitlines()[-1].strip().rstrip('%'))
        if pct > NC_DISK_THRESHOLD and _nc_cooldown_ok('disk_cleanup', 3600):
            has_docker = _docker_available()
            cmd = 'journalctl --vacuum-size=150M 2>&1 | tail -3'
            if has_docker:
                cmd = 'docker system prune -f 2>&1 | tail -4 && ' + cmd
            result, _ = _run2(cmd, timeout=90)
            _nc_emit('disk_cleanup', f'Disk {pct}% > {NC_DISK_THRESHOLD}%', result, 'warn')
    except Exception:
        pass

    # ── Rule 2: Docker container watchdog ─────────────────
    curr_ct = {}
    try:
        fresh = _refresh_docker()  # updates _docker_cache, returns list
        for ct in fresh:
            name  = ct['name']
            is_up = ct['status'].lower().startswith('up')
            curr_ct[name] = is_up

            if any(s in name.lower() for s in _NC_DOCKER_SKIP):
                continue
            if name in _nc_prev_ct and _nc_prev_ct[name] and not is_up:
                if _nc_cooldown_ok(f'docker:{name}', 300):
                    diag = _nc_diag_logs('docker', name)
                    out2, err2 = _run2(f'docker restart "{name}" 2>&1', timeout=25)
                    ok = 'error' not in (out2 + err2).lower()
                    _nc_emit('container_restart',
                             f'{name} abgestürzt — {diag["label"]}',
                             f'{"OK" if ok else "FAIL"}: {(out2 or err2)[:120]}',
                             'info' if ok else 'error')
    except Exception:
        pass
    finally:
        _nc_prev_ct = curr_ct

    # ── Rule 3: Systemd service watchdog ──────────────────
    curr_svc = {}
    try:
        curr_svc = _refresh_systemd()  # writes to _systemd_cache, no double call
        for unit, info in curr_svc.items():
            state = info['sub']   # running / dead / failed / exited
            curr_svc[unit]['_ok'] = state == 'running'

            prev = _nc_prev_svc.get(unit, {})
            was_ok = prev.get('_ok', True)  # assume ok if first time seen

            # Transition: was running → now failed/dead
            if was_ok and state in ('failed', 'dead') and info['active'] != 'inactive':
                if _nc_cooldown_ok(f'svc:{unit}', 300):
                    diag = _nc_diag_logs('systemd', unit)
                    out2, err2 = _run2(f'systemctl restart "{unit}" 2>&1', timeout=20)
                    ok = not err2 and not out2  # systemctl restart prints nothing on success
                    # Verify
                    check = _run(f'systemctl is-active "{unit}" 2>/dev/null', timeout=5)
                    ok = check == 'active'
                    _nc_emit('service_restart',
                             f'{unit} abgestürzt ({state}) — {diag["label"]}',
                             f'{"OK: active" if ok else "FAIL: " + check}',
                             'info' if ok else 'error')

            # Proactive: service is in failed state (may have failed before agent started)
            elif state == 'failed' and unit not in _nc_prev_svc:
                if _nc_cooldown_ok(f'svc_init:{unit}', 600):
                    diag = _nc_diag_logs('systemd', unit)
                    _nc_emit('service_failed',
                             f'{unit} beim Start bereits im failed-Zustand — {diag["label"]}',
                             diag['advice'], 'warn')
    except Exception:
        pass
    finally:
        _nc_prev_svc = curr_svc

def _nc_loop():
    time.sleep(20)  # let the HTTP server start first
    while True:
        try:
            _nc_tick()
        except Exception as e:
            print(f'[Nanoclaw] tick error: {e}')
        time.sleep(60)

# ══════════════════════════════════════════════════════
# SELF-MANAGEMENT — update / uninstall (remote, token-gated)
# ══════════════════════════════════════════════════════

def _delayed(cmd, delay=1.0):
    """Run a shell command after a short delay (lets HTTP response flush)."""
    def _t():
        time.sleep(delay)
        subprocess.run(cmd, shell=True)
    threading.Thread(target=_t, daemon=True).start()

def self_update(url):
    """Download a new agent from url, validate, replace, restart service."""
    if not url or not url.startswith(('http://', 'https://')):
        return {'ok': False, 'error': 'gültige url erforderlich'}
    try:
        import ssl
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        data = _ulib.urlopen(url, timeout=15, context=ctx).read()
        if len(data) < 500 or b'GL Agent' not in data:
            return {'ok': False, 'error': 'ungültige agent-datei'}
        compile(data, '<new-agent>', 'exec')  # syntax check
        tmp = AGENT_PATH + '.new'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, AGENT_PATH)
        os.chmod(AGENT_PATH, 0o755)
        _nc_emit('agent_update', f'agent aktualisiert von {url}', f'{len(data)} bytes → restart', 'info')
        _delayed('systemctl restart gl-agent || kill -TERM 1', 1.0)
        return {'ok': True, 'msg': f'aktualisiert ({len(data)} bytes), starte neu…', 'version': AGENT_VERSION}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}

def self_uninstall():
    """Stop, disable and remove the agent + its unit/env files."""
    _nc_emit('agent_uninstall', 'deinstallation angefordert', 'entferne service + dateien', 'warn')
    cmd = ('systemctl stop gl-agent; systemctl disable gl-agent; '
           'rm -f /etc/systemd/system/gl-agent.service /etc/gl-agent.env ' + AGENT_PATH + '; '
           'systemctl daemon-reload')
    _delayed(cmd, 1.5)
    return {'ok': True, 'msg': 'agent wird in 1.5s deinstalliert'}

# ══════════════════════════════════════════════════════
# HTTP SERVER
# ══════════════════════════════════════════════════════

class AgentHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _auth(self) -> bool:
        if ALLOWED_IPS and self.client_address[0] not in ALLOWED_IPS:
            return False
        return self.headers.get('Authorization', '') == f'Bearer {TOKEN}'

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')
        qs     = parse_qs(parsed.query)
        # /health: unauthentifiziert, leichtgewichtig (Liveness-Check fuer den Hub)
        if path == '/health':
            self._json(200, {'ok': True, 'version': AGENT_VERSION,
                             'hostname': socket.gethostname(), 'ts': int(time.time())})
            return
        if not self._auth():
            self._json(401, {'error': 'Unauthorized'}); return
        try:
            if path in ('', '/'):
                self._json(200, get_status())
            elif path == '/version':
                self._json(200, {'version': AGENT_VERSION, 'hostname': socket.gethostname(),
                                 'uptime_agent_s': int(time.time() - START_TS), 'port': PORT})
            elif path == '/ports':
                st = get_status()
                self._json(200, {'listening_ports': st.get('listening_ports', [])})
            elif path == '/procs':
                self._json(200, {'procs': get_procs()})
            elif path == '/docker':
                self._json(200, {'containers': get_docker()})
            elif path == '/logs':
                self._json(200, {'lines': get_logs()})
            elif path == '/nanoclaw/events':
                with _nc_lock:
                    evs = list(reversed(_nc_events[-50:]))
                self._json(200, {'events': evs, 'enabled': NC_ENABLED})
            elif path == '/nanoclaw/diagnose':
                name = qs.get('container', [''])[0]
                if not name:
                    self._json(400, {'error': 'container param required'}); return
                self._json(200, nc_diagnose(name))
            else:
                self._json(404, {'error': 'Not found'})
        except Exception as e:
            self._json(500, {'error': str(e)})

    def do_POST(self):
        if not self._auth():
            self._json(401, {'error': 'Unauthorized'}); return
        path = urlparse(self.path).path.rstrip('/')
        n    = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(n) or b'{}')
        try:
            if path == '/restart':
                if not _check_restart_rate(self.client_address[0]):
                    self._json(429, {'ok': False, 'error': 'Rate limit: max 10 restarts/min'}); return
                self._json(200, restart_service(body.get('name', '')))
            elif path == '/update':
                self._json(200, self_update(body.get('url', '')))
            elif path == '/uninstall':
                if not body.get('confirm'):
                    self._json(400, {'ok': False, 'error': 'confirm:true erforderlich'}); return
                self._json(200, self_uninstall())
            elif path == '/nanoclaw/cleanup':
                if _nc_cooldown_ok('disk_cleanup_manual', 30):
                    result, _ = _run2(
                        'docker system prune -f 2>&1 | tail -4 && '
                        'journalctl --vacuum-size=150M 2>&1 | tail -2',
                        timeout=90)
                    _nc_emit('disk_cleanup', 'Manuell ausgelöst', result, 'info')
                    self._json(200, {'ok': True, 'result': result})
                else:
                    self._json(429, {'ok': False, 'error': 'Cooldown aktiv'})
            else:
                self._json(404, {'error': 'Not found'})
        except Exception as e:
            self._json(500, {'error': str(e)})

# ══════════════════════════════════════════════════════
# SELF-REGISTRATION (Heartbeat an den Hub)
# ══════════════════════════════════════════════════════
def _register_once():
    """Meldet sich beim Hub mit Identitaet + Kurz-Inventar. Best-effort."""
    try:
        st = get_status()
        payload = {
            'hostname':        st.get('hostname'),
            'ip':              st.get('ip'),
            'agent_version':   AGENT_VERSION,
            'port':            PORT,
            'cpu_pct':         st.get('cpu_pct'),
            'mem_pct':         st.get('mem_pct'),
            'disk':            st.get('disk'),
            'uptime_h':        st.get('uptime_h'),
            'listening_ports': st.get('listening_ports'),
            'docker_ok':       st.get('docker_ok'),
            'nanoclaw':        NC_ENABLED,
            'ts':              int(time.time()),
        }
        req = _ulib.Request(f'{GL_HUB_URL}/api/agent/register',
                            data=json.dumps(payload).encode(), method='POST')
        req.add_header('Authorization', f'Bearer {TOKEN}')
        req.add_header('Content-Type', 'application/json')
        _ulib.urlopen(req, timeout=5).read()
        return True
    except Exception:
        return False

def _register_loop():
    time.sleep(5)
    while True:
        try:
            _register_once()
        except Exception:
            pass
        time.sleep(GL_REGISTER_INT)

if __name__ == '__main__':
    hostname = socket.gethostname()
    if not TOKEN:
        raise SystemExit('GL_AGENT_TOKEN ist nicht gesetzt - Agent startet nicht ohne Token')
    print(f'[GL Agent v{AGENT_VERSION}] {hostname} · port {PORT}')
    if GL_REGISTER and GL_HUB_URL:
        threading.Thread(target=_register_loop, daemon=True).start()
        print(f'[Register] Self-registration → {GL_HUB_URL} alle {GL_REGISTER_INT}s')
    if NC_ENABLED:
        threading.Thread(target=_nc_loop, daemon=True).start()
        print(f'[Nanoclaw] Self-healing active · disk_threshold={NC_DISK_THRESHOLD}%')
    srv = http.server.ThreadingHTTPServer((BIND_IP, PORT), AgentHandler)
    if ALLOWED_IPS:
        print(f'[GL Agent v{AGENT_VERSION}] IP allowlist: {", ".join(sorted(ALLOWED_IPS))}')
    srv.serve_forever()
