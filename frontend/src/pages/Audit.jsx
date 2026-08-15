import { useEffect, useMemo, useState } from 'react'
import { getJSON } from '../api.js'

const LABELS = {
  login: '🔓 Login', login_fail: '⛔ Login fehlgeschlagen', logout: '🚪 Logout',
  container_start: '▶ Container Start', container_stop: '⏹ Container Stop', container_restart: '↻ Container Neustart',
  bulk_start: '▶ Mehrere Container Start', bulk_stop: '⏹ Mehrere Container Stop', bulk_restart: '↻ Mehrere Container Neustart',
  lxc_start: '▶ CT Start', lxc_stop: '⏹ CT Stop', lxc_reboot: '↻ CT Reboot', lxc_shutdown: '⏻ CT Shutdown',
  task_create: '➕ Aufgabe erstellt', task_update: '✎ Aufgabe geändert', task_delete: '🗑 Aufgabe gelöscht',
  task_run: '⚙ Aufgabe gelaufen', task_run_manual: '▶ Aufgabe manuell gestartet',
  auto_create: '➕ Automation erstellt', ai_analyze: '✦ KI-Analyse', nc_diagnose: '🩺 Diagnose',
  inv_scan: '▤ Inventar-Scan', inv_scan_all: '▤ Inventar-Scan (alle)', host_meta: '✎ Host-Metadaten',
  token_create: '🔑 Token erstellt', user_create: '👤 Benutzer erstellt', user_delete: '👤 Benutzer gelöscht',
  password_change: '🔑 Passwort geändert', mfa_enable: '🔐 2FA aktiviert', mfa_disable: '🔓 2FA deaktiviert',
  ssh_open: '⌨ SSH geöffnet', ssh_close: '⌨ SSH geschlossen', restart: '↻ Neustart (API)',
}
const FILTERS = {
  all: 'Alles', auth: 'Logins', actions: 'Aktionen (Container/CT)', tasks: 'Aufgaben', admin: 'Admin/Benutzer',
}
const GROUPS = {
  auth: ['login', 'login_fail', 'logout'],
  actions: ['container_start', 'container_stop', 'container_restart', 'bulk_start', 'bulk_stop', 'bulk_restart', 'lxc_start', 'lxc_stop', 'lxc_reboot', 'lxc_shutdown', 'restart'],
  tasks: ['task_create', 'task_update', 'task_delete', 'task_run', 'task_run_manual'],
  admin: ['user_create', 'user_delete', 'password_change', 'mfa_enable', 'mfa_disable', 'token_create', 'host_meta'],
}

export default function Audit() {
  const [rows, setRows] = useState([])
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')

  async function load() { setRows(await getJSON('/api/audit').catch(() => [])) }
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [])

  const shown = useMemo(() => {
    const ql = q.trim().toLowerCase()
    return rows.filter(r => {
      if (filter !== 'all' && !(GROUPS[filter] || []).includes(r.action)) return false
      if (ql && !`${r.user} ${r.action} ${r.host} ${r.detail}`.toLowerCase().includes(ql)) return false
      return true
    })
  }, [rows, q, filter])

  return (
    <>
      <div className="group-title">Protokoll — wer hat wann was gemacht</div>
      <div className="panel" style={{ marginBottom: 16, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <input className="inp" placeholder="🔍 filtern (Benutzer, Aktion, Host …)" value={q}
          onChange={e => setQ(e.target.value)} style={{ minWidth: 240 }} />
        <select className="inp" value={filter} onChange={e => setFilter(e.target.value)}>
          {Object.entries(FILTERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span className="muted" style={{ fontSize: 12 }}>{shown.length} Einträge</span>
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={load}>↻ Aktualisieren</button>
      </div>

      <div className="panel" style={{ overflowX: 'auto' }}>
        <table className="tbl" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--muted,#888)' }}>
              <th style={{ padding: '6px 10px' }}>Zeit</th>
              <th style={{ padding: '6px 10px' }}>Benutzer</th>
              <th style={{ padding: '6px 10px' }}>Aktion</th>
              <th style={{ padding: '6px 10px' }}>Ziel</th>
              <th style={{ padding: '6px 10px' }}>Detail</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={5} className="muted" style={{ padding: 12 }}>Keine Einträge.</td></tr>}
            {shown.map((r, i) => {
              const fail = r.action === 'login_fail'
              return (
                <tr key={i} style={{ borderTop: '1px solid var(--border,#222)', background: fail ? 'rgba(248,113,113,.08)' : 'transparent' }}>
                  <td style={{ padding: '6px 10px', whiteSpace: 'nowrap', color: 'var(--muted,#888)' }}>{fmt(r.ts)}</td>
                  <td style={{ padding: '6px 10px', fontWeight: 600 }}>{r.user || '—'}</td>
                  <td style={{ padding: '6px 10px', whiteSpace: 'nowrap' }}>{LABELS[r.action] || r.action}</td>
                  <td style={{ padding: '6px 10px' }}>{r.host || '—'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--muted,#aaa)', wordBreak: 'break-word' }}>{r.detail || ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function fmt(ts) {
  try { return new Date(ts).toLocaleString() } catch { return ts }
}
