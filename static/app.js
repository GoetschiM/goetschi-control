// Goetschi Labs Dashboard v6
'use strict';

let liveData    = null;
let searchQuery = '';
let currentSection = 'overview';
let currentView    = 'grid';

const SECTION_LABELS = {
    overview: 'All Hosts',
    infra:    'Infrastructure',
    app:      'Applications',
    ai:       'AI Services',
    agent:    'Agents',
    voice:    'Voice',
    core:     'Core',
    links:    'External Links',
    flow:     'Network Flow',
};

const STATUS_COLORS = { online: '#10b981', degraded: '#b45309', offline: '#b91c1c', unknown: '#374151' };

const CAT_COLORS = {
    infra:   '#06b6d4',
    app:     '#8b5cf6',
    ai:      '#10b981',
    agent:   '#6366f1',
    voice:   '#f97316',
    core:    '#3b82f6',
    trading: '#d97706',
};

// ── History buffers for bottom metric charts ──
const cpuHist = [];
const ramHist = [];
const netHist = [];

// ── Per-host network rate tracking (cumulative bytes → bps) ──
const _netPrev = {};  // { hostKey: { ts, rx, tx } }

function getNetRate(hostKey, netMap) {
    if (!netMap || typeof netMap !== 'object') return null;
    let rx = 0, tx = 0;
    for (const iface of Object.values(netMap)) {
        rx += iface.rx_bytes || 0;
        tx += iface.tx_bytes || 0;
    }
    const now = Date.now();
    const prev = _netPrev[hostKey];
    _netPrev[hostKey] = { ts: now, rx, tx };
    if (!prev || prev.rx === 0) return null;
    const dt = (now - prev.ts) / 1000;
    if (dt < 1) return null;
    return { rx_bps: Math.max(0, (rx - prev.rx) / dt), tx_bps: Math.max(0, (tx - prev.tx) / dt) };
}

function fmtBps(bps) {
    if (bps == null) return '—';
    if (bps < 1024) return bps.toFixed(0) + ' B/s';
    if (bps < 1024 * 1024) return (bps / 1024).toFixed(1) + ' KB/s';
    return (bps / (1024 * 1024)).toFixed(2) + ' MB/s';
}

// ════════════════════════════════════════
// CLOCK
// ════════════════════════════════════════
function tickClock() {
    const el = document.getElementById('topbar-time');
    if (el) {
        const now = new Date();
        el.textContent = now.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
}
setInterval(tickClock, 1000);
tickClock();

// ════════════════════════════════════════
// FETCH / REFRESH
// ════════════════════════════════════════
async function fetchData() {
    try {
        const resp = await fetch('/api/live');
        if (resp.status === 401) { location.href = '/login'; return; }
        liveData = await resp.json();
        updateAll(liveData);
    } catch (e) {
        console.warn('[Dashboard] Fetch failed:', e);
    }
}

function updateAll(data) {
    liveData = data;
    // Pre-compute net rates from cumulative agent bytes
    for (const h of (data.hosts || [])) {
        const net = h.agent?.net;
        if (net) h._netRate = getNetRate(h.key, net);
    }
    updateStats(data);
    updateNavBadges(data);
    updateAlerts(data);
    updateGrid(data);
    updateMetrics(data);
    updateRightPanel(data);
    updateDiscoveryBanner(data);
    if (currentSection === 'flow') renderMetricsGrid(data);
    const footer = document.getElementById('rp-footer');
    if (footer) footer.textContent = '// last_sync: ' + new Date().toLocaleTimeString('de-CH');
}

// ════════════════════════════════════════
// ALERTS
// ════════════════════════════════════════
// Alert dismiss: persisted in sessionStorage
const _dismissedAlerts = new Set(JSON.parse(sessionStorage.getItem('gl_dismissed_alerts') || '[]'));
function _alertId(a) { return `${a.key}:${a.msg}`; }
function dismissAlert(id, ev) {
    ev.stopPropagation();
    _dismissedAlerts.add(id);
    sessionStorage.setItem('gl_dismissed_alerts', JSON.stringify([..._dismissedAlerts]));
    if (liveData) updateAlerts(liveData);
}
function clearAllAlerts() {
    if (liveData) (liveData.alerts || []).forEach(a => _dismissedAlerts.add(_alertId(a)));
    sessionStorage.setItem('gl_dismissed_alerts', JSON.stringify([..._dismissedAlerts]));
    if (liveData) updateAlerts(liveData);
}

function updateAlerts(data) {
    const allAlerts = data.alerts || [];
    const alerts    = allAlerts.filter(a => !_dismissedAlerts.has(_alertId(a)));
    const badge  = document.getElementById('alert-badge');
    const panel  = document.getElementById('alert-panel');
    if (!badge) return;

    const critCount = alerts.filter(a => a.severity === 'critical').length;
    const predCount = alerts.filter(a => a.severity === 'predict').length;
    const total     = alerts.length;

    if (total === 0) {
        badge.style.display = 'none';
    } else {
        badge.style.display = 'flex';
        badge.textContent   = total;
        badge.className     = 'alert-badge ' + (critCount ? 'crit' : predCount ? 'predict' : 'warn');
    }

    if (!panel) return;
    const sevIcon = {critical: '!!', warn: '!', predict: '⚡'};
    panel.innerHTML = alerts.length ? `
        <div style="display:flex;justify-content:flex-end;padding:4px 8px">
            <button onclick="clearAllAlerts()" style="font-size:9px;background:none;border:1px solid var(--border);color:var(--txt-dim);padding:2px 8px;border-radius:4px;cursor:pointer">alle löschen</button>
        </div>` + alerts.map(a => `
        <div class="alert-item ${a.severity}" onclick="setSection('${a.key}');closeAlertPanel()">
            <span class="alert-sev">${sevIcon[a.severity] || '!'}</span>
            <span class="alert-host">${a.host}</span>
            <span class="alert-msg">${a.msg}</span>
            <span class="alert-ip">${a.ip}</span>
            <button onclick="dismissAlert('${_alertId(a)}',event)" style="margin-left:auto;background:none;border:none;color:var(--txt-dim);cursor:pointer;font-size:11px">✕</button>
        </div>`).join('')
    : '<div class="alert-empty">// no active alerts</div>';
}

function toggleAlertPanel() {
    const p = document.getElementById('alert-panel');
    if (p) p.classList.toggle('hidden');
}
function closeAlertPanel() {
    document.getElementById('alert-panel')?.classList.add('hidden');
}

function updateDiscoveryBanner(data) {
    const banner = document.getElementById('discovery-banner');
    const msg    = document.getElementById('discovery-msg');
    const status = document.getElementById('discovery-status');
    if (!banner) return;
    const n = data.new_host_count || 0;
    if (n > 0) {
        banner.classList.remove('hidden');
        if (msg) msg.textContent = `Auto-Discovery: ${n} neue Host(s) gefunden · letzter Scan: ${data.discovery_ts ? new Date(data.discovery_ts*1000).toLocaleTimeString('de-CH') : '—'}`;
    } else {
        banner.classList.add('hidden');
    }
    if (status) status.textContent = data.prom_ok ? '● prom ok' : '○ prom n/a';
}

// ════════════════════════════════════════
// STATS ROW
// ════════════════════════════════════════
function updateStats(data) { _updateStats(data); }

function _updateStats(data) {
    const s = data.summary || {};
    setText('stat-online',   s.online   ?? 0);
    setText('stat-degraded', s.degraded ?? 0);
    setText('stat-offline',  s.offline  ?? 0);

    const total  = (s.online ?? 0) + (s.degraded ?? 0);
    const grand  = s.total || 1;
    const health = Math.round(total / grand * 100);
    setText('health-pct', health + '%');

    const arc = document.getElementById('health-arc');
    if (arc) arc.style.strokeDashoffset = 201 - (201 * health / 100);

    const rtts = data.hosts.filter(h => h.ping_rtt).map(h => h.ping_rtt);
    const avg  = rtts.length ? Math.round(rtts.reduce((a, b) => a + b, 0) / rtts.length) : null;
    setText('stat-latency', avg ? avg + 'ms' : '—');

    // UniFi stats in topbar
    const u = data.unifi || {};
    setText('stat-wifi-clients',  u.clients_wifi  ?? '—');
    setText('stat-wired-clients', u.clients_wired ?? '—');
    const wan = u.wan || {};
    if (wan.rx_bytes != null) {
        setText('stat-wan-rx', fmtBps(wan.rx_bytes));
        setText('stat-wan-tx', fmtBps(wan.tx_bytes));
    }
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

// ════════════════════════════════════════
// NAV BADGES
// ════════════════════════════════════════
function updateNavBadges(data) {
    const cats = {};
    for (const h of data.hosts) {
        const c = h.category || 'other';
        cats[c] = (cats[c] || 0) + (h.status === 'online' ? 1 : 0);
    }
    const ids = { infra: 'nb-infra', app: 'nb-app', ai: 'nb-ai', agent: 'nb-agent', voice: 'nb-voice', core: 'nb-core' };
    for (const [cat, elId] of Object.entries(ids)) {
        const el = document.getElementById(elId);
        if (el) el.textContent = cats[cat] ?? 0;
    }
}

// ════════════════════════════════════════
// NAVIGATION (WORKING!)
// ════════════════════════════════════════
const PAGE_VIEWS = ['grid-view', 'flow-view', 'logs-view', 'settings-view', 'automations-view'];

function setSection(id) {
    currentSection = id;

    document.querySelectorAll('.nav-item[data-section]').forEach(el => {
        el.classList.toggle('active', el.dataset.section === id);
    });

    const breadcrumb = document.getElementById('topbar-section');
    if (breadcrumb) breadcrumb.textContent = id;
    setText('section-title-txt', `// ${id}`);

    const isPageView = id === 'logs' || id === 'settings' || id === 'automations';
    const isFlow     = id === 'flow';

    PAGE_VIEWS.forEach(v => document.getElementById(v)?.classList.add('hidden'));
    document.querySelector('.stats-row')?.classList.toggle('hidden', isPageView);
    document.querySelector('.metrics-row')?.classList.toggle('hidden', isPageView);

    if (isPageView) {
        document.getElementById(id + '-view')?.classList.remove('hidden');
        if (id === 'logs')        loadLogs();
        if (id === 'settings')    loadSettings();
        if (id === 'automations') loadAutomations();
        return;
    }

    if (isFlow) {
        document.getElementById('flow-view')?.classList.remove('hidden');
        document.getElementById('btn-view-flow')?.classList.add('active');
        document.getElementById('btn-view-grid')?.classList.remove('active');
        if (liveData) renderFlowDiagram(liveData);
        return;
    }

    document.getElementById('grid-view')?.classList.remove('hidden');
    document.getElementById('btn-view-grid')?.classList.add('active');
    document.getElementById('btn-view-flow')?.classList.remove('active');

    const linksSection = document.getElementById('links-section');
    const gridEl       = document.getElementById('services-grid');
    if (id === 'links') {
        linksSection?.classList.remove('hidden');
        gridEl?.classList.add('hidden');
        renderLinks(liveData);
    } else {
        linksSection?.classList.add('hidden');
        gridEl?.classList.remove('hidden');
        if (liveData) renderGrid(liveData);
    }
}

// ── Settings ────────────────────────────────────
let _settingsData = null;

async function loadSettings() {
    try {
        const r = await fetch('/api/settings');
        _settingsData = await r.json();
    } catch(e) { _settingsData = null; }
    renderSettings();
    loadApiTokens();
    if (_settingsData) _renderTelegramStatus(_settingsData);
    loadBackupStatus();
}

async function loadApiTokens() {
    const el = document.getElementById('api-token-list');
    if (!el) return;
    try {
        const r = await fetch('/api/tokens');
        const tokens = await r.json();
        el.innerHTML = tokens.length ? tokens.map(t => `
            <div class="token-row" style="gap:6px;align-items:center">
                <span class="token-name" style="min-width:80px">${t.name}</span>
                <code class="token-val" style="flex:1;font-size:9px;overflow:hidden;text-overflow:ellipsis" title="${t.token}">${t.token}</code>
                <button onclick="copyText('${t.token}')" class="pg-action-btn" style="font-size:9px">copy</button>
                <button onclick="deleteApiToken('${t.id}')" class="pg-action-btn" style="font-size:9px;color:var(--offline-fg)">✕</button>
            </div>`).join('')
        : '<div class="table-empty">// keine tokens — klicke "+ token"</div>';
    } catch(e) { el.innerHTML = '<div class="table-empty">Fehler</div>'; }
}

function showCreateTokenForm() {
    document.getElementById('api-token-form')?.classList.remove('hidden');
    document.getElementById('new-token-name')?.focus();
}
function hideCreateTokenForm() {
    document.getElementById('api-token-form')?.classList.add('hidden');
    const i = document.getElementById('new-token-name'); if (i) i.value = '';
}

async function createApiToken() {
    const name = document.getElementById('new-token-name')?.value.trim();
    if (!name) return;
    const r = await fetch('/api/tokens', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ name })
    });
    const d = await r.json();
    if (d.ok) {
        hideCreateTokenForm();
        await loadApiTokens();
        // Show the token once
        const notice = document.createElement('div');
        notice.className = 'copy-notice';
        notice.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);max-width:400px;word-break:break-all;padding:12px 16px;font-size:11px;z-index:9999';
        notice.textContent = `Token für "${name}": ${d.token}`;
        document.body.appendChild(notice);
        navigator.clipboard?.writeText(d.token);
        setTimeout(() => notice.remove(), 8000);
    }
}

async function deleteApiToken(id) {
    if (!confirm('Token löschen?')) return;
    await fetch(`/api/tokens/${id}`, { method: 'DELETE' });
    await loadApiTokens();
}

function renderSettings() {
    const d = _settingsData;
    if (!d) return;

    const base = d.dashboard_url || window.location.origin;
    const tok  = d.agent_token   || '';

    // Fill token display
    const tv = document.getElementById('agent-token-val');
    if (tv) tv.textContent = tok;

    // Build install commands
    const linuxCmd = `curl -sSL ${base}/static/agent/install.sh | GL_AGENT_TOKEN=${tok} bash`;
    const macCmd   = linuxCmd;
    const winCmd   = `$env:GL_AGENT_TOKEN="${tok}"; irm ${base}/static/agent/install.ps1 | iex`;
    const setCmd   = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setCmd('install-cmd-linux', linuxCmd);
    setCmd('install-cmd-mac',   macCmd);
    setCmd('install-cmd-win',   winCmd);

    // Hermes tokens
    const tl = document.getElementById('token-list');
    if (tl) {
        if (!d.hermes_agents || !d.hermes_agents.length) {
            tl.innerHTML = '<div class="table-empty">No tokens configured.</div>';
        } else {
            tl.innerHTML = d.hermes_agents.map(t => `
                <div class="token-row">
                    <span class="token-name">${t.name}</span>
                    <code class="token-val">${t.token_hint}</code>
                </div>`).join('');
        }
    }

    // Connected agents — use cached liveData (avoids triggering systemctl spikes)
    const tbody = document.getElementById('agents-tbody');
    if (!tbody || !d.agent_hosts) return;

    const renderAgentTable = () => {
        const hosts = (liveData && liveData.hosts) ? liveData.hosts : [];
        const hostMap = Object.fromEntries(hosts.map(h => [h.key, h]));
        tbody.innerHTML = d.agent_hosts.map(h => {
            const lh = hostMap[h.key];
            const ag = lh && lh.agent;
            const ok = lh && lh.status !== 'offline' && ag && ag.hostname;
            const dot = (lh && lh.status === 'online')
                ? '<span class="tbl-dot online"></span>online'
                : '<span class="tbl-dot offline"></span>offline';
            const cpuVal = ok ? (ag.cpu_pct != null ? ag.cpu_pct : (lh.metrics && lh.metrics.cpu)) : null;
            const memVal = ok ? (ag.mem_pct != null ? ag.mem_pct : (lh.metrics && lh.metrics.ram)) : null;
            const dskVal = ok && ag.disk ? ag.disk.pct : null;
            return `<tr>
                <td><span class="tbl-name">${h.name}</span></td>
                <td><code>${h.ip}</code></td>
                <td>${cpuVal != null ? bar(cpuVal) : '—'}</td>
                <td>${memVal != null ? bar(memVal) : '—'}</td>
                <td>${dskVal != null ? bar(dskVal) : '—'}</td>
                <td>${ok ? (ag.uptime_h || 0).toFixed(1) + 'h' : '—'}</td>
                <td>${dot}</td>
            </tr>`;
        }).join('');
    };

    if (liveData) {
        renderAgentTable();
    } else {
        tbody.innerHTML = '<tr><td colspan="7" class="table-empty">// waiting for live data…</td></tr>';
        const waiter = setInterval(() => { if (liveData) { clearInterval(waiter); renderAgentTable(); } }, 500);
    }

    // Category management
    _renderCategoryEditor(d.agent_hosts);
}

async function _renderCategoryEditor(agentHosts) {
    const el = document.getElementById('category-editor');
    if (!el) return;
    // Fetch current meta
    let meta = {};
    try { const r = await fetch('/api/host_meta'); meta = await r.json(); } catch(e) {}
    const hosts = (liveData && liveData.hosts) ? liveData.hosts : [];
    const allHosts = [...hosts];
    const cats = ['infra', 'ai', 'agent', 'app', 'voice', 'core', 'trading', 'other'];

    el.innerHTML = `
    <div class="detail-section-title" style="margin-top:16px">// host kategorien anpassen</div>
    <table class="data-table" style="font-size:11px">
        <thead><tr><th>Host</th><th>IP</th><th>Kategorie</th><th>Anzeigename</th><th></th></tr></thead>
        <tbody>${allHosts.map(h => {
            const m = meta[h.key] || {};
            const catSel = cats.map(c => `<option value="${c}" ${(m.category||h.category)===c?'selected':''}>${c}</option>`).join('');
            return `<tr>
                <td>${h.icon || ''} ${h.name}</td>
                <td><code style="font-size:10px">${h.ip}</code></td>
                <td><select id="cat-${h.key}" style="background:var(--bg-card);color:var(--txt);border:1px solid var(--border);border-radius:4px;padding:2px 4px;font-size:10px">${catSel}</select></td>
                <td><input id="dn-${h.key}" type="text" placeholder="${h.name}" value="${m.display_name||''}" style="background:var(--bg-card);color:var(--txt);border:1px solid var(--border);border-radius:4px;padding:2px 6px;font-size:10px;width:120px"></td>
                <td><button onclick="saveHostMeta('${h.key}')" class="pg-action-btn">speichern</button></td>
            </tr>`;
        }).join('')}</tbody>
    </table>`;
}

async function saveHostMeta(key) {
    const cat = document.getElementById('cat-' + key)?.value;
    const dn  = document.getElementById('dn-' + key)?.value || '';
    const r = await fetch(`/api/host_meta/${key}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ category: cat, display_name: dn })
    });
    const d = await r.json();
    if (d.ok) {
        const notice = document.createElement('div');
        notice.className = 'copy-notice';
        notice.textContent = `✓ ${key} gespeichert`;
        document.body.appendChild(notice);
        setTimeout(() => notice.remove(), 1400);
    }
}

function bar(pct) {
    const p   = Math.min(100, Math.max(0, pct || 0));
    const col = p > 85 ? 'var(--offline)' : p > 65 ? 'var(--warn)' : 'var(--online)';
    return `<span class="mini-bar-wrap"><span class="mini-bar-fill" style="width:${p}%;background:${col}"></span></span><span style="font-size:10px;margin-left:4px">${p.toFixed(0)}%</span>`;
}

function selectInstallTab(tab, btn) {
    document.querySelectorAll('.install-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    ['linux','mac','win'].forEach(t => {
        document.getElementById('install-' + t)?.classList.toggle('hidden', t !== tab);
    });
}

function copyText(text) {
    navigator.clipboard.writeText(text.trim()).then(() => {
        const notice = document.createElement('div');
        notice.className = 'copy-notice';
        notice.textContent = 'copied!';
        document.body.appendChild(notice);
        setTimeout(() => notice.remove(), 1400);
    });
}

// ── Logs ─────────────────────────────────────────
let _allLogs    = [];
let _ncEvents   = [];
let _logFilter  = 'all';
let _logSource  = 'audit';  // 'audit' | 'nanoclaw'

async function loadLogs() {
    const tbody = document.getElementById('audit-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="table-empty">// loading…</td></tr>';
    try {
        const [auditR, ncR] = await Promise.all([
            fetch('/api/audit'),
            fetch('/api/nanoclaw/events'),
        ]);
        _allLogs  = await auditR.json();
        _ncEvents = await ncR.json();
    } catch(e) { _allLogs = []; _ncEvents = []; }
    renderLogs();
}

function renderLogs() {
    const tbody = document.getElementById('audit-tbody');
    if (!tbody) return;

    if (_logSource === 'nanoclaw') {
        _renderNcLogs(tbody);
        return;
    }

    const rows = _logFilter === 'all'
        ? _allLogs
        : _allLogs.filter(r => r.action && r.action.includes(_logFilter));
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="table-empty">// no entries</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(r => {
        const ts  = r.ts ? r.ts.replace('T',' ').slice(0,19) : '—';
        const act = r.action || '';
        const cls = act.includes('ssh')     ? 'log-act-ssh'
                  : act.includes('restart') ? 'log-act-restart'
                  : act.includes('nanoclaw') || act.includes('disk') || act.includes('agent_restart') ? 'log-act-nc'
                  : act.includes('login')   ? 'log-act-login'
                  : '';
        return `<tr>
            <td><code class="log-ts">${ts}</code></td>
            <td>${r.user || '—'}</td>
            <td><span class="log-act ${cls}">${act}</span></td>
            <td>${r.host || '—'}</td>
            <td class="log-detail">${r.detail || '—'}</td>
        </tr>`;
    }).join('');
}

function _renderNcLogs(tbody) {
    if (!_ncEvents.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="table-empty">// no nanoclaw events yet — system is healthy</td></tr>';
        return;
    }
    tbody.innerHTML = _ncEvents.map(e => {
        const ts  = e.ts_str ? e.ts_str.replace('T',' ') : new Date(e.ts*1000).toISOString().replace('T',' ').slice(0,19);
        const sev = e.severity || 'info';
        const cls = sev === 'error' ? 'log-act-error' : sev === 'warn' ? 'log-act-warn' : 'log-act-nc';
        return `<tr>
            <td><code class="log-ts">${ts}</code></td>
            <td><span class="log-act ${cls}">${sev}</span></td>
            <td>${e.action || '—'}</td>
            <td>${e.host || '—'}</td>
            <td class="log-detail">${e.detail || ''} → <span style="opacity:.7">${e.result || ''}</span></td>
        </tr>`;
    }).join('');
}

function filterLogs(type, btn) {
    _logFilter  = type;
    _logSource  = 'audit';
    document.querySelectorAll('.log-filter').forEach(b => b.classList.remove('active'));
    btn?.classList.add('active');
    renderLogs();
}

function showNcLogs(btn) {
    _logSource = 'nanoclaw';
    document.querySelectorAll('.log-filter').forEach(b => b.classList.remove('active'));
    btn?.classList.add('active');
    renderLogs();
}

// ── Automations / Cron Scheduler ──────────────
let _crons = [];

async function loadAutomations() {
    try {
        const r = await fetch('/api/crons');
        _crons = await r.json();
    } catch(e) { _crons = []; }
    renderCrons();
    populateCronHostSelect();
}

function populateCronHostSelect() {
    const sel = document.getElementById('cf-host');
    if (!sel || sel.dataset.filled) return;
    if (liveData && liveData.hosts) {
        sel.innerHTML = liveData.hosts
            .map(h => `<option value="${h.key}">${h.name} (${h.ip})</option>`)
            .join('');
        sel.dataset.filled = '1';
    }
}

function renderCrons() {
    const tbody = document.getElementById('crons-tbody');
    const badge = document.getElementById('cron-count');
    if (badge) badge.textContent = _crons.length;
    if (!tbody) return;
    if (!_crons.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="table-empty">// no jobs — click "+ new job" to create one</td></tr>';
        return;
    }
    tbody.innerHTML = _crons.map(c => {
        const ok      = c.last_ok === 1;
        const lastRun = c.last_run ? c.last_run.slice(0,16).replace('T',' ') : 'never';
        const nextRun = c.next_run ? c.next_run.slice(0,16).replace('T',' ') : '—';
        const statCls = c.last_run == null ? '' : (ok ? 'log-act-login' : 'log-act-restart');
        const statTxt = c.last_run == null ? '—' : (ok ? 'ok' : 'error');
        const enBtn   = `<button class="pg-action-btn" onclick="toggleCron('${c.id}',${c.enabled ? 0 : 1})">${c.enabled ? 'disable' : 'enable'}</button>`;
        const runBtn  = `<button class="pg-action-btn" onclick="runCronNow('${c.id}','${c.name}')">▶ run</button>`;
        const delBtn  = `<button class="pg-action-btn" style="color:var(--offline-fg)" onclick="deleteCron('${c.id}')">✕</button>`;
        const outBtn  = c.last_result ? `<button class="pg-action-btn" onclick="showCronResult('${c.id}','${c.name}')">output</button>` : '';
        return `<tr style="opacity:${c.enabled ? 1 : .45}">
            <td><span class="tbl-name">${c.name}</span><br><span style="font-size:9px;color:var(--txt-dim)">next: ${nextRun}</span></td>
            <td><code>${c.host_key}</code></td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><code>${c.command}</code></td>
            <td>${fmtInterval(c.interval_min)}</td>
            <td><code class="log-ts">${lastRun}</code></td>
            <td><span class="log-act ${statCls}">${statTxt}</span></td>
            <td style="white-space:nowrap">${runBtn} ${enBtn} ${outBtn} ${delBtn}</td>
        </tr>`;
    }).join('');
}

function fmtInterval(min) {
    if (min < 60)  return `${min}min`;
    if (min < 1440) return `${min/60}h`;
    return `${min/1440}d`;
}

const PREDEFINED_CMDS = [
    { label: '── System ──', cmd: '', group: true },
    { label: 'Disk Usage',          cmd: 'df -h' },
    { label: 'RAM Status',          cmd: 'free -h' },
    { label: 'System Logs (50)',    cmd: 'journalctl -n 50 --no-pager' },
    { label: 'Uptime',              cmd: 'uptime && w' },
    { label: '── Docker ──', cmd: '', group: true },
    { label: 'Container Liste',     cmd: 'docker ps -a --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}"' },
    { label: 'Docker Logs (tail)',  cmd: 'docker logs --tail 50 $(docker ps -q | head -1) 2>&1' },
    { label: 'Docker Stats',        cmd: 'docker stats --no-stream --format "table {{.Name}}\\t{{.CPUPerc}}\\t{{.MemUsage}}"' },
    { label: 'Docker prune',        cmd: 'docker system prune -f' },
    { label: '── Updates ──', cmd: '', group: true },
    { label: 'Check Updates',       cmd: 'apt update -qq && apt list --upgradable 2>/dev/null | grep -v Listing' },
    { label: 'Security Updates',    cmd: 'apt update -qq && apt-get -s upgrade | grep "Inst" | grep -i security' },
    { label: '── Nanoclaw ──', cmd: '', group: true },
    { label: 'Agent Status',        cmd: 'systemctl status gl-agent --no-pager' },
    { label: 'Agent Logs',          cmd: 'journalctl -u gl-agent -n 30 --no-pager' },
    { label: 'Restart Agent',       cmd: 'systemctl restart gl-agent && sleep 2 && systemctl status gl-agent --no-pager' },
];

function usePredefinedCmd() {
    const sel = document.getElementById('cf-predefined');
    const cmd = sel?.value;
    if (cmd) {
        const input = document.getElementById('cf-cmd');
        if (input) input.value = cmd;
        sel.value = '';
    }
}

function showCronForm() {
    document.getElementById('cron-form')?.classList.remove('hidden');
    populateCronHostSelect();
    // Fill predefined dropdown
    const pd = document.getElementById('cf-predefined');
    if (pd && !pd.dataset.filled) {
        pd.innerHTML = '<option value="">── Vorgefertigte Befehle ──</option>' +
            PREDEFINED_CMDS.map(c => c.group
                ? `<option value="" disabled style="color:var(--txt-dim)">${c.label}</option>`
                : `<option value="${c.cmd.replace(/"/g,'&quot;')}">${c.label}</option>`
            ).join('');
        pd.dataset.filled = '1';
    }
}
function hideCronForm() { document.getElementById('cron-form')?.classList.add('hidden'); }

async function saveCron() {
    const name  = document.getElementById('cf-name')?.value.trim() || 'job';
    const host  = document.getElementById('cf-host')?.value;
    const cmd   = document.getElementById('cf-cmd')?.value.trim();
    const mins  = parseInt(document.getElementById('cf-interval')?.value || '60');
    if (!host || !cmd) { alert('Host und Befehl sind pflicht'); return; }
    const r = await fetch('/api/crons', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ name, host_key: host, command: cmd, interval_min: mins })
    });
    if (r.ok) {
        hideCronForm();
        await loadAutomations();
    }
}

async function toggleCron(id, enabled) {
    await fetch(`/api/crons/${id}`, { method: 'PATCH',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ enabled }) });
    await loadAutomations();
}

async function deleteCron(id) {
    if (!confirm('Delete this job?')) return;
    await fetch(`/api/crons/${id}`, { method: 'DELETE' });
    await loadAutomations();
}

async function runCronNow(id, name) {
    await fetch(`/api/crons/${id}/run`, { method: 'POST' });
    const notice = document.createElement('div');
    notice.className = 'copy-notice';
    notice.textContent = `▶ ${name} triggered`;
    document.body.appendChild(notice);
    setTimeout(() => notice.remove(), 2000);
    setTimeout(() => loadAutomations(), 3000);
}

function showCronResult(id, name) {
    const c = _crons.find(x => x.id === id);
    if (!c) return;
    document.getElementById('cron-result-title').textContent = `// output: ${name}`;
    document.getElementById('cron-result-output').textContent = c.last_result || '(empty)';
    document.getElementById('cron-result-card').style.display = '';
}

function setView(v) {
    currentView = v;
    document.getElementById('grid-view')?.classList.toggle('hidden', v !== 'grid');
    document.getElementById('flow-view')?.classList.toggle('hidden', v !== 'flow');
    document.getElementById('btn-view-grid')?.classList.toggle('active', v === 'grid');
    document.getElementById('btn-view-flow')?.classList.toggle('active', v === 'flow');
    if (v === 'flow' && liveData) renderFlowDiagram(liveData);
}

// ════════════════════════════════════════
// SEARCH
// ════════════════════════════════════════
function onSearch(q) {
    searchQuery = q.toLowerCase().trim();
    if (liveData) renderGrid(liveData);
}

// ════════════════════════════════════════
// GRID — Container-centric cards
// ════════════════════════════════════════
function updateGrid(data) {
    renderGrid(data);
}

function renderGrid(data) {
    const grid = document.getElementById('services-grid');
    if (!grid) return;

    let hosts = data.hosts || [];

    // Filter by section (category)
    if (currentSection !== 'overview') {
        hosts = hosts.filter(h => h.category === currentSection);
    }

    // Filter by search query
    if (searchQuery) {
        hosts = hosts.filter(h => {
            const needle = searchQuery;
            if (h.name.toLowerCase().includes(needle)) return true;
            if (h.ip.includes(needle)) return true;
            if ((h.key || '').includes(needle)) return true;
            if (h.services?.some(s => s.name.toLowerCase().includes(needle))) return true;
            return false;
        });
    }

    const count = hosts.length;
    const online = hosts.filter(h => h.status === 'online').length;
    setText('svc-count', `${online} / ${count} online`);

    if (count === 0) {
        grid.innerHTML = '<div class="svc-loading">Keine Hosts für diese Kategorie</div>';
        return;
    }

    // Sort: online first, then degraded, then offline
    hosts = [...hosts].sort((a, b) => {
        const ord = { online: 0, degraded: 1, offline: 2 };
        return (ord[a.status] ?? 3) - (ord[b.status] ?? 3);
    });

    grid.innerHTML = hosts.map(h => buildHostCard(h)).join('');
}

function buildHostCard(h) {
    const statusColor = STATUS_COLORS[h.status] || STATUS_COLORS.unknown;
    const catClass    = `cat-${h.category || 'other'}`;
    const svcs        = h.services || [];
    const rtt         = h.ping_rtt ? h.ping_rtt.toFixed(0) + 'ms' : '—';
    const m           = h.metrics || {};

    const ctBadge   = h.ct_id ? `<span class="host-ct">CT${h.ct_id}</span>` : '';
    const autoBadge = h.auto  ? `<span class="host-auto-badge">AUTO</span>` : '';

    // Prometheus metric bars
    let metricHtml = '';
    if (m.cpu != null || m.ram != null) {
        const cpu = m.cpu ?? 0;
        const ram = m.ram ?? 0;
        metricHtml = `
        <div class="host-metrics">
            <div class="hm-item">
                <span class="hm-label">CPU</span>
                <div class="hm-bar-wrap"><div class="hm-bar cpu" style="width:${Math.min(100,cpu)}%"></div></div>
                <span class="hm-val">${cpu.toFixed(0)}%</span>
            </div>
            <div class="hm-item">
                <span class="hm-label">RAM</span>
                <div class="hm-bar-wrap"><div class="hm-bar ram" style="width:${Math.min(100,ram)}%"></div></div>
                <span class="hm-val">${ram.toFixed(0)}%</span>
            </div>
        </div>`;
    }

    // Service rows — show all, with [Open] button if URL exists
    const MAX_SHOW = 6;
    const visibleSvcs = svcs.slice(0, MAX_SHOW);
    const hiddenCount = svcs.length - MAX_SHOW;

    const svcRows = visibleSvcs.map(s => {
        const openBtn = s.url
            ? `<a class="svc-open-btn" href="${s.url}" target="_blank" onclick="event.stopPropagation()">Open ↗</a>`
            : '';
        const rttTxt = s.rtt ? `${s.rtt.toFixed(0)}ms` : (s.status === 'online' ? 'OK' : '');
        return `
        <div class="host-svc-row">
            <span class="svc-dot ${s.status}"></span>
            <span class="svc-name">${s.name}</span>
            <span class="svc-rtt">${rttTxt}</span>
            ${openBtn}
        </div>`;
    }).join('');

    const moreHtml = hiddenCount > 0
        ? `<div class="host-svc-more">+${hiddenCount} weitere Services…</div>` : '';

    // Sparkline from ping history
    const hist = h.ping_history || [];
    const sparkHtml = buildSparkline(hist);

    const statusLabel = { online: '[ONLINE]', degraded: '[DEGRADED]', offline: '[OFFLINE]' }[h.status] || '[UNKNOWN]';
    const svcBadge = svcs.length > 0
        ? `<span class="host-svc-badge">${h.svc_online ?? 0}/${h.svc_total ?? 0} svcs</span>` : '';
    const sshCapable = h.ct_id || h.key === 'casaos';
    const sshBtn = sshCapable
        ? `<button class="svc-ssh-btn" onclick="event.stopPropagation();openSSH('${h.key}')">⌨ SSH</button>` : '';
    const slaBadgeHtml = h.sla_30d != null ? slaBadge(h.sla_30d) : '';
    const predBadge = h.disk_pred_days != null && h.disk_pred_days < 14
        ? `<span class="pred-badge">💾${h.disk_pred_days}d</span>` : '';

    return `
    <div class="host-card cat-${h.category || 'other'} s-${h.status}" onclick="openDetail('${h.key}')">
        <div class="host-card-hdr" onclick="event.stopPropagation();openDetail('${h.key}')">
            <div class="host-info">
                <div class="host-name">${h.name}</div>
                <div class="host-meta">
                    <span class="host-status-dot ${h.status}"></span>
                    <span class="host-ip">${h.ip}</span>
                    ${ctBadge}${autoBadge}
                    <span class="host-rtt">${rtt}</span>
                </div>
            </div>
            ${metricHtml}
        </div>
        <div class="host-svc-list">
            ${svcRows || '<div class="host-svc-more">Keine Services konfiguriert</div>'}
            ${moreHtml}
        </div>
        <div class="host-card-ftr">
            <span class="host-status-text ${h.status}">${statusLabel}</span>
            ${svcBadge}
            ${slaBadgeHtml}
            ${predBadge}
            ${sshBtn}
            <div class="sparkline-wrap" style="margin-left:auto">${sparkHtml}</div>
        </div>
    </div>`;
}

function buildSparkline(hist) {
    if (!hist.length) return '';
    const maxRtt = Math.max(...hist.map(p => p.rtt || 0), 1);
    return hist.slice(-16).map(p => {
        const h  = p.ok && p.rtt ? Math.round((p.rtt / maxRtt) * 18) : 2;
        const bg = p.ok ? '#22c55e' : '#ef4444';
        return `<span class="sparkline-bar" style="height:${h}px;background:${bg}"></span>`;
    }).join('');
}

// ════════════════════════════════════════
// LINKS SECTION
// ════════════════════════════════════════
function renderLinks(data) {
    const grid = document.getElementById('links-grid');
    if (!grid || !data) return;
    const links = data.external || [];
    grid.innerHTML = links.map(l => `
        <a class="link-card" href="${l.url}" target="_blank">
            <span class="link-icon">${l.icon}</span>
            <div>
                <div class="link-name">${l.name}</div>
                <div class="link-desc">${l.desc || ''}</div>
            </div>
        </a>
    `).join('');
}

// ════════════════════════════════════════
// BOTTOM METRICS
// ════════════════════════════════════════
function updateMetrics(data) {
    // Aggregate Prometheus CPU/RAM across all hosts with metrics
    const hostsWithMetrics = data.hosts.filter(h => h.metrics && h.metrics.cpu != null);
    if (hostsWithMetrics.length) {
        const avgCpu = hostsWithMetrics.reduce((a, h) => a + h.metrics.cpu, 0) / hostsWithMetrics.length;
        const avgRam = hostsWithMetrics.reduce((a, h) => a + h.metrics.ram, 0) / hostsWithMetrics.length;
        const netOut = hostsWithMetrics.reduce((a, h) => a + (h.metrics.net_out_mbps || 0), 0);

        cpuHist.push(avgCpu);  if (cpuHist.length > 20) cpuHist.shift();
        ramHist.push(avgRam);  if (ramHist.length > 20) ramHist.shift();
        netHist.push(netOut);  if (netHist.length > 20) netHist.shift();

        setText('m-cpu',     avgCpu.toFixed(1) + '%');
        setText('m-ram',     avgRam.toFixed(1) + '%');
        setText('m-network', netOut.toFixed(2) + ' Mbps');

        renderMiniChart('chart-cpu', cpuHist, 'cpu');
        renderMiniChart('chart-ram', ramHist, 'ram');
        renderMiniChart('chart-net', netHist, 'net');
    } else {
        // Fallback: sum up ping RTTs
        const rtts = data.hosts.filter(h => h.ping_rtt).map(h => h.ping_rtt);
        if (rtts.length) {
            const avg = rtts.reduce((a, b) => a + b, 0) / rtts.length;
            cpuHist.push(avg); if (cpuHist.length > 20) cpuHist.shift();
            renderMiniChart('chart-cpu', cpuHist, 'cpu');
        }
    }

    // Proxmox storage
    const px = data.proxmox || {};
    if (px.ram_pct != null) {
        const pct = px.ram_pct;
        const fill = document.getElementById('storage-fill');
        if (fill) fill.style.width = pct + '%';
        setText('m-storage', pct.toFixed(1) + '%');
        setText('m-storage-detail', `${px.ram_used_gb}GB / ${px.ram_total_gb}GB RAM`);
    }
}

function renderMiniChart(id, hist, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    const max = Math.max(...hist, 1);
    el.innerHTML = hist.map(v => {
        const h = Math.max(2, Math.round((v / max) * 28));
        return `<div class="mini-bar ${cls}" style="height:${h}px"></div>`;
    }).join('');
}

// ════════════════════════════════════════
// RIGHT PANEL
// ════════════════════════════════════════
function updateRightPanel(data) {
    // LXC list from Proxmox
    const lxcList = document.getElementById('lxc-list');
    const lxcBadge = document.getElementById('lxc-badge');
    const prox = data.proxmox || {};

    if (lxcList && prox.lxcs) {
        const sorted = [...prox.lxcs].sort((a, b) => {
            if (a.status === b.status) return a.id - b.id;
            return a.status === 'running' ? -1 : 1;
        });
        if (lxcBadge) lxcBadge.textContent = `${prox.lxc_running}/${prox.lxc_total} running`;
        lxcList.innerHTML = sorted.map(c => `
            <div class="lxc-row" onclick="openDetailById(${c.id})">
                <span class="lxc-dot ${c.status === 'running' ? 'running' : 'stopped'}"></span>
                <span class="lxc-name">${c.name || 'CT' + c.id}</span>
                <span class="lxc-id">CT${c.id}</span>
            </div>
        `).join('');
    } else if (lxcList) {
        // Fallback: show hosts
        const sorted = [...data.hosts].sort((a, b) => {
            if (a.status === b.status) return 0;
            return a.status === 'online' ? -1 : 1;
        });
        if (lxcBadge) lxcBadge.textContent = `${data.summary.online}/${data.summary.total}`;
        lxcList.innerHTML = sorted.map(h => `
            <div class="lxc-row" onclick="openDetail('${h.key}')">
                <span class="lxc-dot ${h.status === 'online' ? 'running' : 'stopped'}"></span>
                <span class="lxc-name">${h.name}</span>
                <span class="lxc-id">${h.ip}</span>
            </div>
        `).join('');
    }

    // AI services status
    const aiMap = {
        'nova': ['nova', 'LiteLLM (lokal)', 'AI Router'],
        'mcphub': ['mcphub', 'MCPHub'],
        'nova_ollama': ['nova', 'Ollama'],
        'nova_router': ['nova', 'AI Router'],
    };
    function getSvcStatus(hostKey, svcName) {
        if (!data) return null;
        const host = data.hosts.find(h => h.key === hostKey);
        if (!host) return null;
        return host.services?.find(s => s.name === svcName);
    }
    function setStat(id, hostKey, svcName) {
        const svc = getSvcStatus(hostKey, svcName);
        const el  = document.getElementById(id);
        if (!el) return;
        if (svc) {
            el.textContent = svc.status === 'online' ? '● Online' : '● Offline';
            el.style.color = STATUS_COLORS[svc.status] || '#64748b';
        }
    }
    setStat('ai-nova',   'litellm', 'LiteLLM');
    setStat('ai-mcp',    'mcphub',  'MCPHub');
    setStat('ai-ollama', 'nova',    'AI Router');
    setStat('ai-router', 'hermes',  'Hermes API');
}

function openDetailById(ctId) {
    if (!liveData) return;
    const ctMap = {
        100: 'dokploy', 103: 'paperless', 105: 'pgvector', 107: 'mcphub',
        108: 'hermes-apollo', 109: 'influxdb', 110: 'monitoring', 112: 'nova',
        116: 'litellm', 117: 'voice', 118: 'coolify', 401: 'magos', 402: 'orion',
        504: 'mt5-bot4', 505: 'minio', 506: 'qdrant',
    };
    const key = ctMap[ctId];
    if (key) openDetail(key);
}

// ════════════════════════════════════════
// DETAIL MODAL
// ════════════════════════════════════════
function openDetail(key) {
    if (!liveData) return;
    const host = liveData.hosts.find(h => h.key === key);
    if (!host) return;

    const m = host.metrics || {};
    const metaGrid = [
        ['Status',      `<span style="color:${STATUS_COLORS[host.status]}">${host.status.toUpperCase()}</span>`],
        ['IP',          `<code>${host.ip}</code>`],
        ['CT-ID',       host.ct_id ? `CT${host.ct_id}` : '—'],
        ['Ping RTT',    host.ping_rtt ? host.ping_rtt.toFixed(1) + ' ms' : '—'],
        ['CPU',         m.cpu != null ? m.cpu.toFixed(1) + '%' : '—'],
        ['RAM',         m.ram != null ? m.ram.toFixed(1) + '%' : '—'],
        ['Net Out',     m.net_out_mbps != null ? m.net_out_mbps.toFixed(2) + ' Mbps' : '—'],
        ['Disk',        m.disk_pct != null ? m.disk_pct.toFixed(1) + '%' : '—'],
        ['SLA 30d',     host.sla_30d != null ? slaBadge(host.sla_30d) : '—'],
        ['SSL',         host.ssl_min_days != null ? sslBadge(host.ssl_min_days) : '—'],
        ['Disk in',     host.disk_pred_days != null ? `~${host.disk_pred_days}d bis 90%` : '—'],
    ].map(([lbl, val]) => `
        <div class="detail-meta-item">
            <div class="detail-meta-label">${lbl}</div>
            <div class="detail-meta-val">${val}</div>
        </div>
    `).join('');

    // Ping history chart
    const hist = host.ping_history || [];
    const maxRtt = Math.max(...hist.map(p => p.rtt || 0), 1);
    const pingChart = hist.map(p => {
        const h  = p.ok && p.rtt ? Math.round((p.rtt / maxRtt) * 40) : 2;
        const bg = p.ok ? '#22c55e' : '#ef4444';
        return `<div class="detail-ping-bar" style="flex:1;height:${h}px;background:${bg};border-radius:2px 2px 0 0"></div>`;
    }).join('');

    // Services list
    const svcs = host.services || [];
    const svcRows = svcs.map(s => {
        const color = STATUS_COLORS[s.status] || STATUS_COLORS.unknown;
        const openBtn = s.url
            ? `<a class="svc-open-btn" href="${s.url}" target="_blank">Öffnen ↗</a>` : '';
        return `
        <div class="detail-svc-row">
            <span class="detail-svc-status" style="background:${color}"></span>
            <span class="detail-svc-name">${s.name}</span>
            <span class="detail-svc-desc">${s.desc || ''}</span>
            <span class="detail-svc-rtt">${s.rtt ? s.rtt.toFixed(0) + 'ms' : (s.status === 'online' ? 'OK' : s.status)}</span>
            ${openBtn}
        </div>`;
    }).join('');

    const restartBtn = `
        <button class="detail-restart-btn" onclick="restartHost('${key}')">
            ↺ Restart
        </button>`;
    const termBtn = host.ct_id ? `
        <button class="detail-restart-btn" style="background:rgba(99,102,241,.1);border-color:rgba(99,102,241,.3);color:#a78bfa"
            onclick="closeDetail();openSSH('${key}')">
            ⌨ Terminal
        </button>` : '';

    // Agent data (pre-loaded in live data, lazy-load full details separately)
    const agt = host.agent;
    let agentHtml = '';
    if (agt) {
        const disk = agt.disk || {};
        const diskBar = disk.pct != null
            ? `<div class="hm-bar-wrap" style="width:100%;margin:2px 0">
                 <div class="hm-bar cpu" style="width:${Math.min(100,disk.pct)}%;background:${disk.pct>85?'#ef4444':disk.pct>65?'#f59e0b':'#10b981'}"></div>
               </div>` : '';
        const nr = host._netRate;
        const netRow = nr ? `<span class="detail-agent-item"><span class="detail-meta-label">Net rx</span> <span style="color:var(--online-fg)">${fmtBps(nr.rx_bps)}</span></span><span class="detail-agent-item"><span class="detail-meta-label">tx</span> <span style="color:var(--accent-fg)">${fmtBps(nr.tx_bps)}</span></span>` : '';
        agentHtml = `
        <div class="detail-agent-row">
            <span class="detail-agent-item"><span class="detail-meta-label">CPU</span> ${agt.cpu_pct != null ? agt.cpu_pct.toFixed(1)+'%' : '—'}</span>
            <span class="detail-agent-item"><span class="detail-meta-label">Mem</span> ${agt.mem_used_gb != null ? agt.mem_used_gb+'GB / '+agt.mem_total_gb+'GB' : '—'}</span>
            <span class="detail-agent-item"><span class="detail-meta-label">Uptime</span> ${agt.uptime_h != null ? agt.uptime_h.toFixed(1)+'h' : '—'}</span>
            ${netRow}
        </div>
        ${disk.pct != null ? `<div style="margin:2px 0 4px"><span class="detail-meta-label">Disk ${disk.used_gb}GB / ${disk.total_gb}GB (${disk.pct}%)</span>${diskBar}</div>` : ''}`;
    }

    const panel = document.getElementById('detail-panel');
    panel.innerHTML = `
    <div class="detail-sheet" onclick="event.stopPropagation()">
        <div class="detail-hdr">
            <div>
                <div class="detail-title">${host.name}</div>
                <div class="detail-ip">${host.ip}${host.ct_id ? ' · CT' + host.ct_id : ''} · ${host.category || ''}</div>
            </div>
            ${restartBtn}
            ${termBtn}
            <span class="detail-close" onclick="closeDetail()">✕</span>
        </div>
        <div class="detail-body">
            <div>
                <div class="detail-section-title">System Info</div>
                <div class="detail-meta-grid">${metaGrid}</div>
                ${agentHtml}
            </div>
            ${hist.length ? `
            <div>
                <div class="detail-section-title">Ping History (letzte ${hist.length} Messungen)</div>
                <div class="detail-ping-chart">${pingChart}</div>
            </div>` : ''}
            ${svcs.length ? `
            <div>
                <div class="detail-section-title">Services (${host.svc_online}/${host.svc_total} online)</div>
                <div class="detail-svc-list">${svcRows}</div>
            </div>` : ''}
            <div id="agent-detail-section"></div>
            <div id="proc-detail-section"></div>
            <div id="hist-section"></div>
            <div id="dep-section"></div>
        </div>
    </div>`;
    panel.classList.remove('hidden');
    panel.onclick = closeDetail;

    // Auto-load agent + processes for agent-capable hosts
    const hasAgent = host.ct_id || ['casaos','smarthome'].includes(key);
    if (hasAgent) {
        loadAgentDetail(key);
        loadProcesses(key);
        loadMetricsHistory(key, document.getElementById('hist-section'));
    }
    loadDependencies(key, document.getElementById('dep-section'));
    if (key === 'unifi')   loadUnifiDetail();
    if (key === 'litellm') loadLitellmDetail();
    if (key === 'dokploy') loadDokployDetail();
}

async function loadLitellmDetail() {
    const sec = document.getElementById('agent-detail-section');
    if (!sec) return;
    sec.innerHTML = '<div class="svc-loading">// loading litellm…</div>';
    try {
        const r = await fetch('/api/litellm');
        const d = await r.json();
        const alive = d.alive ? `<span style="color:var(--online-fg)">alive</span>` : `<span style="color:var(--offline-fg)">unreachable</span>`;
        const db    = d.db ? `<span style="color:var(--online-fg)">connected</span>` : `<span style="color:var(--warn-fg)">not connected</span>`;
        const modelRows = (d.models || []).map(m => `
            <div class="detail-svc-row">
                <span class="detail-svc-status" style="background:var(--online-fg)"></span>
                <span class="detail-svc-name">${m}</span>
                <span class="detail-svc-rtt" style="font-size:9px;opacity:.6">model</span>
            </div>`).join('');
        sec.innerHTML = `
        <div class="detail-agent-row" style="margin-top:8px">
            <span class="detail-agent-item"><span class="detail-meta-label">Status</span> ${alive}</span>
            <span class="detail-agent-item"><span class="detail-meta-label">DB</span> ${db}</span>
            <span class="detail-agent-item"><span class="detail-meta-label">Models</span> ${d.model_count || 0}</span>
        </div>
        <div class="detail-section-title" style="margin-top:10px">// models</div>
        <div class="detail-svc-list">${modelRows || '<div class="host-svc-more">Keine Models</div>'}</div>`;
    } catch(e) {
        sec.innerHTML = `<div class="svc-loading">Fehler: ${e.message}</div>`;
    }
}

async function loadDokployDetail() {
    const sec = document.getElementById('agent-detail-section');
    if (!sec) return;
    sec.innerHTML = '<div class="svc-loading">// loading dokploy apps…</div>';
    try {
        const r = await fetch('/api/dokploy');
        const d = await r.json();
        const apps = d.apps || [];
        const apiNote = d.has_api ? '' : `<div style="font-size:9px;color:var(--txt-dim);margin-top:4px">// Dokploy API-Token nicht konfiguriert — zeigt GL-Agent-Daten</div>`;
        const appRows = apps.map(a => {
            const color = a.status === 'online' ? 'var(--online-fg)' : 'var(--offline-fg)';
            const portBadge = a.ports ? `<span style="font-size:9px;color:var(--txt-dim)">${a.ports.slice(0,30)}</span>` : '';
            return `<div class="detail-svc-row">
                <span class="detail-svc-status" style="background:${color}"></span>
                <span class="detail-svc-name">${a.name}</span>
                <span class="detail-svc-desc">${(a.image||'').split(':')[0].split('/').pop()}</span>
                <span class="detail-svc-rtt" style="font-size:9px;opacity:.6">${a.status_raw.slice(0,18)}</span>
                ${portBadge}
            </div>`;
        }).join('');
        sec.innerHTML = `
        <div class="detail-agent-row" style="margin-top:8px">
            <span class="detail-agent-item"><span class="detail-meta-label">Apps total</span> ${d.apps_total}</span>
            <span class="detail-agent-item"><span class="detail-meta-label">Online</span> <span style="color:var(--online-fg)">${d.apps_online}</span></span>
        </div>
        ${apiNote}
        <div class="detail-section-title" style="margin-top:10px">// deployed_apps</div>
        <div class="detail-svc-list">${appRows || '<div class="host-svc-more">Keine Apps</div>'}</div>`;
    } catch(e) {
        sec.innerHTML = `<div class="svc-loading">Fehler: ${e.message}</div>`;
    }
}

async function loadUnifiDetail() {
    const sec = document.getElementById('agent-detail-section');
    if (!sec) return;
    sec.innerHTML = '<div class="svc-loading">// loading unifi data…</div>';
    try {
        const r = await fetch('/api/unifi');
        const u = await r.json();
        if (!u || u.error) { sec.innerHTML = '<div class="svc-loading">UniFi nicht erreichbar</div>'; return; }
        const wan = u.wan || {};
        const fmtBytes = b => b > 1e9 ? (b/1e9).toFixed(1)+' GB' : b > 1e6 ? (b/1e6).toFixed(1)+' MB' : (b/1e3).toFixed(0)+' KB';
        const clientRows = (u.top_clients || []).slice(0, 15).map(c => {
            const icon = c.type === 'wifi' ? 'W' : 'E';
            const rssi = c.rssi != null ? ` ${c.rssi}dBm` : '';
            return `<div class="detail-svc-row">
                <span class="detail-svc-status" style="background:var(--online-fg)"></span>
                <span class="detail-svc-name" style="min-width:120px">${c.name}</span>
                <span class="detail-svc-desc">${c.ip}</span>
                <span class="detail-svc-rtt" style="font-size:9px;color:var(--txt-dim)">[${icon}${rssi}]</span>
                <span class="detail-svc-rtt" style="font-size:9px;color:var(--txt-dim)">↓${fmtBytes(c.rx)} ↑${fmtBytes(c.tx)}</span>
            </div>`;
        }).join('');
        sec.innerHTML = `
        <div class="detail-agent-row" style="margin-top:8px">
            <span class="detail-agent-item"><span class="detail-meta-label">WAN IP</span> ${wan.ip || '—'}</span>
            <span class="detail-agent-item"><span class="detail-meta-label">Status</span> <span style="color:var(--online-fg)">${wan.status || '—'}</span></span>
            <span class="detail-agent-item"><span class="detail-meta-label">Latenz</span> ${wan.latency ?? '—'}ms</span>
            <span class="detail-agent-item"><span class="detail-meta-label">rx</span> <span style="color:var(--online-fg)">${fmtBps(wan.rx_bytes)}</span></span>
            <span class="detail-agent-item"><span class="detail-meta-label">tx</span> <span style="color:var(--accent-fg)">${fmtBps(wan.tx_bytes)}</span></span>
        </div>
        <div class="detail-section-title" style="margin-top:10px">// clients (${u.clients_total} total · ${u.clients_wifi} wifi · ${u.clients_wired} wired)</div>
        <div class="detail-svc-list">${clientRows || '<div class="host-svc-more">Keine Clients</div>'}</div>`;
    } catch(e) {
        sec.innerHTML = `<div class="svc-loading">Fehler: ${e.message}</div>`;
    }
}

async function loadProcesses(key) {
    const sec = document.getElementById('proc-detail-section');
    if (!sec) return;
    try {
        const r = await fetch(`/api/processes/${key}`);
        const d = await r.json();
        const procs = d.procs || [];
        if (!procs.length) { sec.innerHTML = ''; return; }
        sec.innerHTML = `
        <div class="detail-section-title" style="margin-top:14px">// top_processes</div>
        <table class="data-table" style="font-size:10px">
            <thead><tr><th>user</th><th>pid</th><th>cpu%</th><th>mem%</th><th>command</th></tr></thead>
            <tbody>${procs.map(p => `<tr>
                <td>${p.user}</td>
                <td>${p.pid}</td>
                <td style="color:${parseFloat(p.cpu)>50?'var(--offline-fg)':parseFloat(p.cpu)>20?'var(--warn-fg)':'var(--txt-muted)'}">${p.cpu}</td>
                <td style="color:${parseFloat(p.mem)>50?'var(--offline-fg)':parseFloat(p.mem)>20?'var(--warn-fg)':'var(--txt-muted)'}">${p.mem}</td>
                <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt-muted)">${p.cmd}</td>
            </tr>`).join('')}</tbody>
        </table>`;
    } catch(e) { /* no agent */ }
}

async function loadAgentDetail(key) {
    const sec = document.getElementById('agent-detail-section');
    if (!sec) return;
    sec.innerHTML = '<div class="svc-loading">// loading agent data…</div>';
    try {
        const resp = await fetch(`/api/agent/${key}`);
        const d    = await resp.json();
        if (d.error) { sec.innerHTML = `<div class="svc-loading">Agent offline: ${d.error}</div>`; return; }

        const docker    = (d.docker?.containers || []);
        const logs      = (d.logs?.lines || []);
        const dockerItems = docker.filter(c => c.source !== 'systemd');
        const svcItems    = docker.filter(c => c.source === 'systemd');

        const renderContainer = c => {
            const up = c.status?.toLowerCase().startsWith('up');
            const diagBtn = !up
                ? `<button class="svc-open-btn" style="cursor:pointer;border:none;background:rgba(239,68,68,.15);color:#ef4444;font-size:9px;padding:1px 6px"
                      onclick="ncDiagnose('${key}','${c.name}',this)">diag</button>` : '';
            return `<div class="detail-svc-row">
                <span class="detail-svc-status" style="background:${up?'#10b981':'#ef4444'}"></span>
                <span class="detail-svc-name">${c.name}</span>
                <span class="detail-svc-desc">${(c.image||'').split(':')[0]}</span>
                <span class="detail-svc-rtt" style="font-size:9px;opacity:.6">${(c.status||'').slice(0,20)}</span>
                <button class="svc-open-btn" style="cursor:pointer;border:none;background:#0e1220;color:#6366f1;font-size:9px;padding:1px 6px"
                    onclick="agentRestart('${key}','${c.name}')">↺</button>
                ${diagBtn}
            </div>`;
        };

        const renderSvc = c => {
            const up  = c.status?.toLowerCase().startsWith('up') || c.status?.includes('running');
            const diagBtn = !up
                ? `<button class="svc-open-btn" style="cursor:pointer;border:none;background:rgba(239,68,68,.15);color:#ef4444;font-size:9px;padding:1px 6px"
                      onclick="ncDiagnoseSystemd('${key}','${c.name}',this)">diag</button>` : '';
            return `<div class="detail-svc-row">
                <span class="detail-svc-status" style="background:${up?'#10b981':'#ef4444'}"></span>
                <span class="detail-svc-name">${c.name}</span>
                <span class="detail-svc-desc" style="color:var(--txt-dim)">${(c.image||'').slice(0,40)}</span>
                <span class="detail-svc-rtt" style="font-size:9px;opacity:.6">${(c.status||'').slice(0,20)}</span>
                ${diagBtn}
            </div>`;
        };

        const dockerHtml = [
            dockerItems.length
                ? `<div class="detail-section-title" style="margin-top:8px">// docker</div>` + dockerItems.map(renderContainer).join('')
                : '',
            svcItems.length
                ? `<div class="detail-section-title" style="margin-top:10px">// systemd_services</div>` + svcItems.map(renderSvc).join('')
                : '',
        ].join('') || '<div class="host-svc-more">Keine Services</div>';

        const logsHtml = logs.slice(0, 20).map(l =>
            `<div class="log-line ${l.level}">${l.msg}</div>`
        ).join('');

        sec.innerHTML = `
        <div class="detail-section-title" style="margin-top:12px">// docker_containers</div>
        <div class="detail-svc-list">${dockerHtml}</div>
        ${logs.length ? `
        <div class="detail-section-title" style="margin-top:12px">// system_logs</div>
        <div class="loki-log-box" style="max-height:160px;overflow-y:auto">${logsHtml}</div>` : ''}`;
    } catch (e) {
        sec.innerHTML = `<div class="svc-loading">Fehler: ${e.message}</div>`;
    }
}

async function agentRestart(hostKey, containerName) {
    if (!confirm(`Docker container "${containerName}" neu starten?`)) return;
    try {
        const resp = await fetch(`/api/agent/${hostKey}/restart`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: containerName })
        });
        const d = await resp.json();
        alert(d.ok ? `OK: ${d.msg}` : `FAIL: ${d.error}`);
        if (d.ok) loadAgentDetail(hostKey);
    } catch (e) {
        alert('FAIL: ' + e.message);
    }
}

async function ncDiagnoseSystemd(hostKey, unitName, btn) {
    const orig = btn.textContent;
    btn.textContent = '…'; btn.disabled = true;
    try {
        const resp = await fetch(`/api/nanoclaw/diagnose/${hostKey}/${encodeURIComponent(unitName)}?source=systemd`);
        const d = await resp.json();
        const row = btn.closest('.detail-svc-row');
        let box = row.nextElementSibling;
        if (!box || !box.classList.contains('nc-diag-box')) {
            box = document.createElement('div');
            box.className = 'nc-diag-box';
            row.parentNode.insertBefore(box, row.nextSibling);
        }
        box.innerHTML = `
            <div class="nc-diag-label">[Nanoclaw/systemd] ${d.label || '?'}</div>
            <div class="nc-diag-advice">${d.advice || ''}</div>
            ${d.logs ? `<pre class="nc-diag-logs">${d.logs.slice(-600)}</pre>` : ''}`;
    } catch(e) {
        alert('Diagnose-Fehler: ' + e.message);
    } finally {
        btn.textContent = orig; btn.disabled = false;
    }
}

async function ncDiagnose(hostKey, containerName, btn) {
    const orig = btn.textContent;
    btn.textContent = '…';
    btn.disabled = true;
    try {
        const resp = await fetch(`/api/nanoclaw/diagnose/${hostKey}/${encodeURIComponent(containerName)}`);
        const d = await resp.json();
        if (!d.ok && d.advice) { alert(`Diagnose fehlgeschlagen: ${d.advice}`); return; }
        // Show result inline below the row
        const row  = btn.closest('.detail-svc-row');
        let box = row.nextElementSibling;
        if (!box || !box.classList.contains('nc-diag-box')) {
            box = document.createElement('div');
            box.className = 'nc-diag-box';
            row.parentNode.insertBefore(box, row.nextSibling);
        }
        box.innerHTML = `
            <div class="nc-diag-label">[Nanoclaw] ${d.label}</div>
            <div class="nc-diag-advice">${d.advice}</div>
            ${d.logs ? `<pre class="nc-diag-logs">${d.logs.slice(-600)}</pre>` : ''}`;
    } catch(e) {
        alert('Diagnose-Fehler: ' + e.message);
    } finally {
        btn.textContent = orig;
        btn.disabled = false;
    }
}

function closeDetail() {
    document.getElementById('detail-panel')?.classList.add('hidden');
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

// ════════════════════════════════════════
// RMM — RESTART
// ════════════════════════════════════════
async function restartHost(key) {
    if (!confirm(`Container/Service "${key}" wirklich neu starten?`)) return;
    try {
        const resp = await fetch(`/api/restart/${key}`, { method: 'POST' });
        const data = await resp.json();
        alert(data.ok ? '✅ ' + data.message : '❌ ' + data.error);
        if (data.ok) setTimeout(fetchData, 3000);
    } catch (e) {
        alert('❌ Fehler: ' + e.message);
    }
}

// ════════════════════════════════════════
// METRICS GRID (replaces Flow/SVG view)
// ════════════════════════════════════════
function renderMetricsGrid(data) {
    const container = document.getElementById('metrics-grid-view');
    if (!container) return;
    const hosts = (data.hosts || []).filter(h => !['_internet','unifi','proxmox'].includes(h.key));

    const sorted = [...hosts].sort((a, b) => {
        const getPct = h => {
            const ag = h.agent || {};
            return Math.max(ag.cpu_pct || 0, (h.metrics || {}).cpu || 0);
        };
        return getPct(b) - getPct(a);
    });

    container.innerHTML = sorted.map(h => {
        const ag  = h.agent || {};
        const m   = h.metrics || {};
        const cpu = ag.cpu_pct ?? m.cpu ?? null;
        const mem = ag.mem_pct ?? m.ram ?? null;
        const dsk = ag.disk?.pct ?? null;
        const up  = ag.uptime_h != null ? ag.uptime_h.toFixed(0) + 'h' : '—';

        const mkBar = (val, hi=90, mid=70) => {
            if (val == null) return '<span class="mx-dash">—</span>';
            const p   = Math.min(100, Math.max(0, val));
            const col = p >= hi ? 'var(--offline-fg)' : p >= mid ? 'var(--warn-fg)' : 'var(--online-fg)';
            return `<div class="mx-bar-row">
                <div class="mx-bar-bg"><div class="mx-bar-fill" style="width:${p}%;background:${col}"></div></div>
                <span class="mx-bar-val" style="color:${col}">${p.toFixed(0)}%</span>
            </div>`;
        };

        const sCls  = h.status === 'online' ? 's-online' : h.status === 'degraded' ? 's-degraded' : 's-offline';
        const ct    = h.ct_id ? `<span class="host-ct">CT${h.ct_id}</span>` : '';
        const nr    = h._netRate;
        const netRx = nr ? `<span class="mx-net-rx">rx:${fmtBps(nr.rx_bps)}</span>` : '';
        const netTx = nr ? `<span class="mx-net-tx">tx:${fmtBps(nr.tx_bps)}</span>` : '';

        return `<div class="mx-card ${sCls}" onclick="openDetail('${h.key}')">
            <div class="mx-hdr">
                <span class="host-status-dot ${h.status}"></span>
                <span class="mx-name">${h.name}</span>
                ${ct}
                <span class="mx-ip">${h.ip}</span>
            </div>
            <div class="mx-metrics">
                <div class="mx-row"><span class="mx-label">CPU</span>${mkBar(cpu)}</div>
                <div class="mx-row"><span class="mx-label">RAM</span>${mkBar(mem)}</div>
                <div class="mx-row"><span class="mx-label">DSK</span>${mkBar(dsk, 85, 65)}</div>
            </div>
            <div class="mx-footer">
                <span class="mx-svc">${h.svc_online ?? 0}/${h.svc_total ?? 0} svc</span>
                <span class="mx-up">↑${up}</span>
                <span class="mx-rtt">${h.ping_rtt ? h.ping_rtt.toFixed(0) + 'ms' : '—'}</span>
                ${netRx}${netTx}
            </div>
        </div>`;
    }).join('');
}

function renderFlowDiagram(data) {
    renderMetricsGrid(data);
    return;
    const svg = document.getElementById('flow-svg');
    if (!svg) return;

    const hosts   = data.hosts || [];
    const W       = svg.parentElement?.clientWidth || 900;
    const H       = 680;
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

    // Layout layers
    // Layer 0: Internet (top center)
    // Layer 1: UniFi (center)
    // Layer 2: Proxmox (center)
    // Layer 3+: Container groups by category

    const catOrder = ['infra', 'app', 'ai', 'agent', 'voice', 'core', 'trading'];
    const catHosts = {};
    for (const cat of catOrder) catHosts[cat] = hosts.filter(h => h.category === cat && !['unifi','proxmox'].includes(h.key));
    const allCatHosts = hosts.filter(h => !['unifi','proxmox'].includes(h.key));

    const nodes = [];
    const edges = [];

    // Fixed nodes
    const internet = { id: '_internet', label: '🌍 Internet', x: W/2, y: 50, w: 120, h: 36, color: '#1e40af', status: 'online', key: null };
    const unifi    = { id: 'unifi',   label: '🌐 UniFi UDM', x: W/2, y: 130, w: 130, h: 36, color: '#0e7490', key: 'unifi' };
    const proxmox  = { id: 'proxmox', label: '🖥️ Proxmox VE', x: W/2, y: 220, w: 130, h: 36, color: '#7c3aed', key: 'proxmox' };

    const hUnifi   = hosts.find(h => h.key === 'unifi');
    const hProxmox = hosts.find(h => h.key === 'proxmox');
    unifi.status   = hUnifi?.status   || 'unknown';
    proxmox.status = hProxmox?.status || 'unknown';

    nodes.push(internet, unifi, proxmox);
    edges.push({ from: internet, to: unifi }, { from: unifi, to: proxmox });

    // Container nodes arranged in rows
    const COLS       = 5;
    const NODE_W     = 140;
    const NODE_H     = 48;
    const GAP_X      = 16;
    const GAP_Y      = 18;
    const GRID_TOP   = 286;
    const GRID_LEFT  = (W - (COLS * (NODE_W + GAP_X) - GAP_X)) / 2;

    allCatHosts.forEach((h, i) => {
        const col = i % COLS;
        const row = Math.floor(i / COLS);
        const x   = GRID_LEFT + col * (NODE_W + GAP_X) + NODE_W / 2;
        const y   = GRID_TOP  + row * (NODE_H + GAP_Y) + NODE_H / 2;
        const color = CAT_COLORS[h.category] || '#64748b';
        const node  = { id: h.key, label: h.icon + ' ' + h.name, sublabel: h.ip, x, y, w: NODE_W, h: NODE_H, color, status: h.status, key: h.key };
        nodes.push(node);
        edges.push({ from: proxmox, to: node });
    });

    // Build SVG
    const defs = `<defs>
        <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#1e2a3a"/>
        </marker>
        <filter id="glow">
            <feGaussianBlur stdDeviation="2" result="coloredBlur"/>
            <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
    </defs>`;

    // Draw edges first
    const edgeSvg = edges.map(e => {
        const statusColor = STATUS_COLORS[e.to.status] || '#1e2a3a';
        const opacity = e.to.status === 'offline' ? '0.3' : '0.5';
        return `<line class="flow-edge"
            x1="${e.from.x}" y1="${e.from.y + (e.from.h || 36)/2}"
            x2="${e.to.x}"   y2="${e.to.y - (e.to.h || 36)/2}"
            stroke="${statusColor}" stroke-width="1.5" stroke-opacity="${opacity}"
            stroke-dasharray="${e.to.status === 'offline' ? '4 3' : 'none'}"
            marker-end="url(#arrowhead)"/>`;
    }).join('\n');

    // Draw nodes
    const nodeSvg = nodes.map(n => {
        const col   = n.color || '#1e2a3a';
        const sc    = STATUS_COLORS[n.status] || STATUS_COLORS.unknown;
        const rx    = n.id === '_internet' ? 18 : 8;
        const glow  = n.status === 'online' ? 'filter="url(#glow)"' : '';
        const alpha = n.status === 'offline' ? '0.45' : '1';
        const sub   = n.sublabel ? `<text x="${n.x}" y="${n.y+7}" text-anchor="middle" fill="#64748b" font-size="9" font-family="monospace">${n.sublabel}</text>` : '';
        const dot   = n.id !== '_internet'
            ? `<circle cx="${n.x + n.w/2 - 8}" cy="${n.y - n.h/2 + 8}" r="4" fill="${sc}" ${glow}/>` : '';
        const onclick = n.key ? `onclick="openDetail('${n.key}')"` : '';

        return `<g class="flow-node" ${onclick} opacity="${alpha}">
            <rect x="${n.x - n.w/2}" y="${n.y - n.h/2}" width="${n.w}" height="${n.h}" rx="${rx}"
                fill="${col}22" stroke="${col}" stroke-width="1.5"/>
            <text x="${n.x}" y="${n.y - (sub ? 4 : -4)}" text-anchor="middle" fill="#e2e8f0" font-size="11" font-weight="600" font-family="sans-serif">${n.label}</text>
            ${sub}
            ${dot}
        </g>`;
    }).join('\n');

    svg.innerHTML = defs + edgeSvg + nodeSvg;
}

// ════════════════════════════════════════
// SSH TERMINAL
// ════════════════════════════════════════
let sshTerm    = null;
let sshFit     = null;
let sshSocket  = null;
let sshResizeObs = null;

function openSSH(key) {
    if (!liveData) return;
    const host = liveData.hosts.find(h => h.key === key);
    if (!host) return;
    const SSH_CAPABLE = host.ct_id || ['casaos','smarthome','unifi'].includes(host.key);
    if (!SSH_CAPABLE) { alert('SSH für diesen Host nicht konfiguriert.'); return; }

    const modal = document.getElementById('ssh-modal');
    modal.classList.remove('hidden');

    const nameEl = document.getElementById('ssh-host-label');
    const ipEl   = document.getElementById('ssh-host-ip');
    if (nameEl) nameEl.textContent = host.name;
    if (ipEl)   ipEl.textContent   = host.ip;

    // Dispose previous terminal
    if (sshTerm) { sshTerm.dispose(); sshTerm = null; }
    if (sshResizeObs) { sshResizeObs.disconnect(); sshResizeObs = null; }

    const termEl = document.getElementById('ssh-terminal');
    termEl.innerHTML = '';

    sshTerm = new Terminal({
        theme: {
            background: '#050709',
            foreground: '#c0cce0',
            cursor:     '#6366f1',
            selection:  'rgba(99,102,241,.3)',
            black:      '#0d1117', red: '#f87171', green: '#34d399',
            yellow: '#fbbf24', blue: '#60a5fa', magenta: '#a78bfa',
            cyan: '#22d3ee', white: '#e2e8f0',
        },
        fontFamily: '"JetBrains Mono", "Fira Code", monospace',
        fontSize:   13,
        lineHeight: 1.4,
        cursorBlink: true,
        convertEol:  true,
        scrollback:  2000,
    });

    sshFit = new FitAddon.FitAddon();
    sshTerm.loadAddon(sshFit);
    sshTerm.open(termEl);
    sshTerm.write('\x1b[32m[GL] Verbinde...\x1b[0m\r\n');

    setTimeout(() => { if (sshFit) sshFit.fit(); }, 50);

    // Socket.io connection (reuse or create)
    if (!sshSocket || !sshSocket.connected) {
        sshSocket = io({ transports: ['websocket'] });
    }

    sshSocket.off('ssh_data');
    sshSocket.on('ssh_data', d => { if (sshTerm) sshTerm.write(d.d || ''); });

    const cols = sshTerm.cols || 220;
    const rows = sshTerm.rows || 50;
    sshSocket.emit('ssh_open', { host: key, cols, rows });

    sshTerm.onData(d => sshSocket.emit('ssh_input', { d }));
    sshTerm.onResize(({ cols, rows }) => sshSocket.emit('ssh_resize', { cols, rows }));

    // Auto-fit on window resize
    sshResizeObs = new ResizeObserver(() => { if (sshFit) sshFit.fit(); });
    sshResizeObs.observe(document.getElementById('ssh-terminal-wrap'));
}

function closeSSH() {
    document.getElementById('ssh-modal')?.classList.add('hidden');
    if (sshSocket) sshSocket.emit('ssh_input', { d: 'exit\n' });
    if (sshTerm)   { sshTerm.dispose(); sshTerm = null; }
    if (sshResizeObs) { sshResizeObs.disconnect(); sshResizeObs = null; }
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        if (!document.getElementById('ssh-modal')?.classList.contains('hidden')) {
            closeSSH(); return;
        }
        closeDetail();
    }
});

// ════════════════════════════════════════
// v12 FEATURES
// ════════════════════════════════════════

// ── Loki Search ──────────────────────────────────
function showLokiSearch(btn) {
    _logSource = 'audit';
    document.querySelectorAll('.log-filter').forEach(b => b.classList.remove('active'));
    btn?.classList.add('active');
    document.getElementById('loki-search-panel')?.classList.remove('hidden');
    document.getElementById('loki-search-q')?.focus();
}
function hideLokiSearch() {
    document.getElementById('loki-search-panel')?.classList.add('hidden');
    document.querySelectorAll('.log-filter').forEach(b => b.classList.remove('active'));
    document.querySelector('.log-filter:first-child')?.classList.add('active');
}
async function searchLoki() {
    const q   = document.getElementById('loki-search-q')?.value.trim();
    const res = document.getElementById('loki-search-results');
    if (!q || !res) return;
    res.innerHTML = '<div class="table-empty">// suche…</div>';
    try {
        const r = await fetch(`/api/loki/search?q=${encodeURIComponent(q)}&limit=200`);
        const lines = await r.json();
        if (!lines.length) { res.innerHTML = '<div class="table-empty">// keine Ergebnisse</div>'; return; }
        res.innerHTML = lines.map(l => {
            const t  = new Date(l.ts * 1000).toLocaleTimeString('de-CH');
            const hi = l.msg.replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'), 'gi'), m => `<mark style="background:#3b4310;color:#e3e85a">${m}</mark>`);
            return `<div class="log-line" style="font-size:10px;padding:1px 0"><code style="color:var(--txt-dim);margin-right:6px">${t}</code>${hi}</div>`;
        }).join('');
    } catch(e) {
        res.innerHTML = `<div class="table-empty">Fehler: ${e.message}</div>`;
    }
}

// ── Telegram ─────────────────────────────────────
async function testTelegram() {
    const btn = document.getElementById('tg-test-btn');
    const res = document.getElementById('tg-test-result');
    if (btn) { btn.textContent = '⏳ sende…'; btn.disabled = true; }
    try {
        const r = await fetch('/api/telegram/test', { method: 'POST' });
        const d = await r.json();
        if (res) res.textContent = d.ok ? '✓ gesendet!' : ('✗ ' + (d.error || 'Fehler'));
        if (res) res.style.color = d.ok ? 'var(--online-fg)' : 'var(--offline-fg)';
        setTimeout(() => { if (res) res.textContent = ''; }, 4000);
    } catch(e) {
        if (res) { res.textContent = '✗ ' + e.message; res.style.color = 'var(--offline-fg)'; }
    } finally {
        if (btn) { btn.textContent = '📨 Test senden'; btn.disabled = false; }
    }
}

function _renderTelegramStatus(d) {
    const badge = document.getElementById('tg-status-badge');
    const row   = document.getElementById('tg-status-row');
    if (!badge || !row) return;
    if (d.telegram_configured) {
        badge.textContent = 'active';
        badge.style.color = 'var(--online-fg)';
        row.innerHTML = `<span style="color:var(--online-fg)">● aktiv</span> — Chat-ID: <code>${d.telegram_chat_id || '?'}</code>`;
    } else {
        badge.textContent = 'off';
        badge.style.color = 'var(--txt-dim)';
        row.innerHTML = '<span style="color:var(--warn-fg)">○ nicht konfiguriert</span> — env vars setzen + neu deployen';
    }
}

// ── Backup Monitor ───────────────────────────────
async function loadBackupStatus() {
    const el = document.getElementById('backup-list');
    if (!el) return;
    el.innerHTML = '<div class="table-empty">// loading…</div>';
    try {
        const r = await fetch('/api/backups');
        const d = await r.json();
        if (!d || !d.jobs) { el.innerHTML = '<div class="table-empty">// Proxmox nicht verbunden</div>'; return; }
        const jobs = d.jobs.slice(0, 15);
        if (!jobs.length) { el.innerHTML = '<div class="table-empty">// keine Backup-Jobs</div>'; return; }
        const fmtTs = ts => ts ? new Date(ts * 1000).toLocaleString('de-CH', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
        el.innerHTML = `<table class="data-table" style="font-size:10px">
            <thead><tr><th>VMID</th><th>Status</th><th>Start</th><th>Dauer</th></tr></thead>
            <tbody>${jobs.map(j => `<tr>
                <td><code>${j.id}</code></td>
                <td><span class="log-act ${j.ok ? 'log-act-login' : 'log-act-restart'}">${j.status}</span></td>
                <td>${fmtTs(j.starttime)}</td>
                <td style="color:var(--txt-dim)">${j.duration || '—'}</td>
            </tr>`).join('')}</tbody>
        </table>
        ${d.last_ok ? `<div style="font-size:9px;color:var(--online-fg);margin-top:4px">✓ Letztes OK: ${fmtTs(d.last_ok)}</div>` : ''}`;
    } catch(e) {
        el.innerHTML = `<div class="table-empty">Fehler: ${e.message}</div>`;
    }
}

// ── SLA Badge helper ──────────────────────────────
function slaBadge(pct) {
    if (pct == null) return '';
    const color = pct >= 99.5 ? 'var(--online-fg)' : pct >= 99 ? 'var(--warn-fg)' : 'var(--offline-fg)';
    return `<span class="sla-badge" style="color:${color}">${pct.toFixed(1)}%</span>`;
}

// ── SSL Badge helper ──────────────────────────────
function sslBadge(days) {
    if (days == null) return '';
    const color = days > 60 ? 'var(--online-fg)' : days > 14 ? 'var(--warn-fg)' : 'var(--offline-fg)';
    return `<span class="ssl-badge" style="color:${color}">🔒${days}d</span>`;
}

// ── Metrics history sparkline (SVG) ──────────────
function metricsSpark(values, color='#6366f1', width=120, height=30) {
    if (!values || values.length < 2) return '';
    const max = Math.max(...values, 0.001);
    const pts = values.map((v, i) => {
        const x = (i / (values.length - 1)) * width;
        const y = height - (v / max) * height * 0.85 - 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const last = values[values.length - 1];
    const ly = height - (last / max) * height * 0.85 - 2;
    return `<svg width="${width}" height="${height}" style="display:block;overflow:visible">
        <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" opacity=".8"/>
        <circle cx="${width}" cy="${ly.toFixed(1)}" r="2.5" fill="${color}"/>
    </svg>`;
}

// ── Dependencies in detail panel ──────────────────
async function loadDependencies(key, container) {
    if (!container) return;
    try {
        const r = await fetch('/api/dependencies');
        const d = await r.json();
        const deps     = (d.deps || {})[key] || [];
        const usedBy   = (d.used_by || {})[key] || [];
        if (!deps.length && !usedBy.length) return;
        const hostName = k => {
            const h = liveData?.hosts?.find(h => h.key === k);
            return h ? `${h.icon || ''} ${h.name}` : k;
        };
        const mkLink = k => `<span class="dep-link" onclick="closeDetail();setTimeout(()=>openDetail('${k}'),50)">${hostName(k)}</span>`;
        container.innerHTML = `
        <div class="detail-section-title" style="margin-top:12px">// abhängigkeiten</div>
        <div class="dep-grid">
            ${deps.length ? `<div><div class="dep-label">braucht:</div><div class="dep-items">${deps.map(mkLink).join('')}</div></div>` : ''}
            ${usedBy.length ? `<div><div class="dep-label">genutzt von:</div><div class="dep-items">${usedBy.map(mkLink).join('')}</div></div>` : ''}
        </div>`;
    } catch(e) { /* skip */ }
}

// ── History chart in detail panel ────────────────
async function loadMetricsHistory(hostKey, container) {
    if (!container) return;
    try {
        const [cpu, ram, disk] = await Promise.all([
            fetch(`/api/metrics/${hostKey}/history?metric=cpu&hours=24`).then(r => r.json()),
            fetch(`/api/metrics/${hostKey}/history?metric=ram&hours=24`).then(r => r.json()),
            fetch(`/api/metrics/${hostKey}/history?metric=disk&hours=24`).then(r => r.json()),
        ]);
        if (!cpu.length && !ram.length && !disk.length) return;
        const vals = arr => arr.map(p => p.v);
        const fmtLast = arr => arr.length ? arr[arr.length-1].v.toFixed(1) + '%' : '—';
        container.innerHTML = `
        <div class="detail-section-title" style="margin-top:12px">// 24h_history</div>
        <div class="hist-charts">
            ${cpu.length ? `<div class="hist-item"><span class="hist-label">CPU <span class="hist-val">${fmtLast(cpu)}</span></span>${metricsSpark(vals(cpu), '#6366f1')}</div>` : ''}
            ${ram.length ? `<div class="hist-item"><span class="hist-label">RAM <span class="hist-val">${fmtLast(ram)}</span></span>${metricsSpark(vals(ram), '#10b981')}</div>` : ''}
            ${disk.length ? `<div class="hist-item"><span class="hist-label">Disk <span class="hist-val">${fmtLast(disk)}</span></span>${metricsSpark(vals(disk), '#f59e0b')}</div>` : ''}
        </div>`;
    } catch(e) { /* skip */ }
}

// ════════════════════════════════════════
// INIT
// ════════════════════════════════════════
fetchData();
setInterval(fetchData, 5000);
