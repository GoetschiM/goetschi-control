import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getJSON, usePoll } from '../api.js'
import { Pill, StatusDot, MetricBar } from '../ui.jsx'

const GROUPERS = {
  none: { label: 'Keine', fn: () => '' },
  category: { label: 'Kategorie', fn: h => h.category || 'sonstige' },
  ct: { label: 'Typ', fn: h => (h.ct_id ? 'Proxmox-Container' : 'Hosts & Geräte') },
  status: { label: 'Status', fn: h => STATUS_LABEL[h.status] || 'Unbekannt' },
}
const STATUS_LABEL = { online: 'Online', degraded: 'Eingeschränkt', offline: 'Offline' }
const RANK = { offline: 0, degraded: 1, online: 2 }

function store(k, v) { try { localStorage.setItem(k, v) } catch { /* ignore */ } }
function load(k, d) { try { return localStorage.getItem(k) || d } catch { return d } }

export default function Overview() {
  const { data, loading, error } = usePoll('/api/live', 5000)
  const [groupBy, setGroupBy] = useState(() => load('gc_groupby', 'none'))
  const [view, setView] = useState(() => load('gc_view', 'grid'))
  const [status, setStatus] = useState('all')
  const [q, setQ] = useState('')

  const hosts = data?.hosts || []
  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase()
    return hosts
      .filter(h => status === 'all' || (status === 'problems' ? h.status !== 'online' : h.status === status))
      .filter(h => !t || `${h.name} ${h.ip} ${h.ct_id ?? ''} ${h.os_name ?? ''}`.toLowerCase().includes(t))
      .sort((a, b) => (RANK[a.status] ?? 3) - (RANK[b.status] ?? 3) || (a.ct_id ?? 1e9) - (b.ct_id ?? 1e9) || a.name.localeCompare(b.name))
  }, [hosts, status, q])

  const groups = useMemo(() => {
    const fn = (GROUPERS[groupBy] || GROUPERS.none).fn
    const by = {}
    for (const h of filtered) (by[fn(h)] ||= []).push(h)
    return Object.entries(by).sort((a, b) => a[0].localeCompare(b[0]))
  }, [filtered, groupBy])

  if (loading && !data) return <div className="center-msg">lädt …</div>
  if (error && !data) return <div className="center-msg">Fehler: {String(error.message)}</div>

  const s = data?.summary || {}
  const problems = (s.offline ?? 0) + (s.degraded ?? 0)
  const alerts = data?.alerts || []

  return (
    <>
      <Setup hostCount={hosts.filter(h => h.key !== 'unifi' && h.key !== 'proxmox').length} />

      <div className="summary">
        <Stat k="Hosts gesamt" v={s.total ?? 0} active={status === 'all'} onClick={() => setStatus('all')} />
        <Stat k="Online" v={s.online ?? 0} tone="ok" active={status === 'online'} onClick={() => setStatus('online')} />
        <Stat k="Probleme" v={problems} tone={problems ? 'crit' : ''} active={status === 'problems'} onClick={() => setStatus('problems')}
          hint={problems ? `${s.offline ?? 0} offline · ${s.degraded ?? 0} eingeschränkt` : 'alles in Ordnung'} />
        <Stat k="Aktive Alarme" v={alerts.length} tone={alerts.length ? 'warn' : ''} to="/alerts" />
      </div>

      {alerts.length > 0 && (
        <div className="alert-strip">
          {alerts.slice(0, 3).map((a, i) => (
            <Link key={i} to={a.key ? `/host/${encodeURIComponent(a.key)}` : '/alerts'} className={`alert-chip sev-${a.severity}`}>
              <b>{a.host}</b> {a.msg}
            </Link>
          ))}
          {alerts.length > 3 && <Link to="/alerts" className="muted">+{alerts.length - 3} weitere</Link>}
        </div>
      )}

      <div className="toolbar">
        <input className="inp" id="host-filter" placeholder="Filtern nach Name, IP oder CT …" value={q} onChange={e => setQ(e.target.value)} />
        <div className="seg">
          <span className="muted">Gruppieren</span>
          <select className="inp" id="group-by" value={groupBy} onChange={e => { setGroupBy(e.target.value); store('gc_groupby', e.target.value) }}>
            {Object.entries(GROUPERS).map(([k, g]) => <option key={k} value={k}>{g.label}</option>)}
          </select>
        </div>
        <div className="seg toggle">
          <button className={view === 'grid' ? 'on' : ''} onClick={() => { setView('grid'); store('gc_view', 'grid') }}>Kacheln</button>
          <button className={view === 'list' ? 'on' : ''} onClick={() => { setView('list'); store('gc_view', 'list') }}>Liste</button>
        </div>
      </div>

      {filtered.length === 0 && hosts.length > 0 && <div className="center-msg">Keine Hosts passen zum Filter.</div>}

      {groups.map(([g, hs]) => (
        <section key={g || 'all'}>
          {g && <div className="group-title">{g} · {hs.length}</div>}
          {view === 'grid'
            ? <div className="grid">{hs.map(h => <HostCard key={h.key} h={h} />)}</div>
            : <HostTable hosts={hs} />}
        </section>
      ))}
    </>
  )
}

function Setup({ hostCount }) {
  const [c, setC] = useState(null)
  const [hidden, setHidden] = useState(() => load('gc_setup_hidden', '') === '1')
  useEffect(() => { getJSON('/api/connect').then(setC).catch(() => {}) }, [])
  if (!c || hidden) return null
  const steps = [
    { done: hostCount > 0, label: 'Ersten Host erfassen', hint: 'Agent installieren, Netzwerk scannen oder Host von Hand anlegen', to: '/connect' },
    { done: c.integrations.proxmox, label: 'Proxmox verbinden', hint: 'Container werden dann automatisch erkannt', to: '/settings#integrationen' },
    { done: c.integrations.telegram, label: 'Alarme einrichten', hint: 'Benachrichtigung aufs Handy per Telegram', to: '/settings#integrationen' },
    { done: c.agents > 0, label: 'Agent auf einem Host installieren', hint: 'liefert Docker-Container, Pakete und Details', to: '/connect' },
  ]
  const open = steps.filter(s => !s.done).length
  if (!open) return null
  return (
    <div className="setup">
      <div className="setup-head">
        <div>
          <div className="setup-title">Einrichtung · {steps.length - open} von {steps.length} erledigt</div>
          <div className="muted">Jeder Schritt ist optional. Je mehr verbunden ist, desto mehr zeigt die Übersicht.</div>
        </div>
        <button className="btn ghost" onClick={() => { setHidden(true); store('gc_setup_hidden', '1') }}>Ausblenden</button>
      </div>
      <div className="setup-steps">
        {steps.map(s => (
          <Link key={s.label} to={s.to} className={`setup-step ${s.done ? 'done' : ''}`}>
            <span className="check">{s.done ? '✓' : ''}</span>
            <span><b>{s.label}</b><span className="muted">{s.hint}</span></span>
          </Link>
        ))}
      </div>
    </div>
  )
}

function Stat({ k, v, tone, active, onClick, to, hint }) {
  const body = <><div className="k">{k}</div><div className={`v ${tone || ''}`}>{v}</div>{hint && <div className="muted hint">{hint}</div>}</>
  if (to) return <Link className="stat clickable" to={to}>{body}</Link>
  return <button className={`stat clickable ${active ? 'active' : ''}`} onClick={onClick}>{body}</button>
}

function HostCard({ h }) {
  const m = h.metrics || {}
  return (
    <Link className={`card st-${h.status}`} to={`/host/${encodeURIComponent(h.key)}`}>
      <div className="head">
        <StatusDot status={h.status} />
        <span className="name">{h.name}</span>
        <Pill status={h.status} />
      </div>
      <div className="ip">{h.ip || '—'}{h.ct_id ? ` · CT ${h.ct_id}` : ''}{h.os_name ? ` · ${h.os_name}` : ''}</div>
      {h.status_reason && h.status !== 'online' && <div className="reason">{h.status_reason}</div>}
      <div style={{ marginTop: 10 }}>
        <MetricBar label="CPU" value={m.cpu} />
        <MetricBar label="RAM" value={m.ram} />
      </div>
      <div className="card-foot">
        <span>Dienste {h.svc_online ?? 0}/{h.svc_total ?? 0}</span>
        {h.agent ? <span className="tag ok">Agent</span> : <span className="tag">ohne Agent</span>}
      </div>
    </Link>
  )
}

function HostTable({ hosts }) {
  const go = useNavigate()
  return (
    <div className="table-wrap">
      <table className="tbl">
        <thead><tr><th>Status</th><th>Name</th><th>IP</th><th>CT</th><th>CPU</th><th>RAM</th><th>Dienste</th><th>Agent</th></tr></thead>
        <tbody>
          {hosts.map(h => {
            const m = h.metrics || {}
            return (
              <tr key={h.key} onClick={() => go(`/host/${encodeURIComponent(h.key)}`)}>
                <td><Pill status={h.status} /></td>
                <td className="strong">{h.name}{h.os_name && <div className="muted small">{h.os_name}</div>}</td>
                <td className="mono">{h.ip || '—'}</td>
                <td className="mono">{h.ct_id ?? '—'}</td>
                <td className="num">{m.cpu == null ? '—' : `${m.cpu}%`}</td>
                <td className="num">{m.ram == null ? '—' : `${m.ram}%`}</td>
                <td className="num">{h.svc_online ?? 0}/{h.svc_total ?? 0}</td>
                <td>{h.agent ? <span className="tag ok">ja</span> : <span className="muted">—</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
