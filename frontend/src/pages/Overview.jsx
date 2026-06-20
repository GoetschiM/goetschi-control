import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { usePoll } from '../api.js'
import { Pill, StatusDot, MetricBar } from '../ui.jsx'

const GROUPERS = {
  category: { label: 'Kategorie', fn: h => h.category || 'sonstige' },
  ct: { label: 'CT / Typ', fn: h => (h.ct_id ? `CT${h.ct_id}` : 'extern') },
  ip: { label: 'IP-Bereich', fn: h => (h.ip ? h.ip.split('.').slice(0, 3).join('.') + '.x' : '—') },
  status: { label: 'Status', fn: h => h.status || 'unknown' },
}

export default function Overview() {
  const { data, loading, error } = usePoll('/api/live', 5000)
  const [groupBy, setGroupBy] = useState(() => localStorage.getItem('gc_groupby') || 'category')

  function changeGroup(g) { setGroupBy(g); localStorage.setItem('gc_groupby', g) }

  const groups = useMemo(() => {
    const hosts = data?.hosts || []
    const fn = (GROUPERS[groupBy] || GROUPERS.category).fn
    const by = {}
    for (const h of hosts) (by[fn(h)] ||= []).push(h)
    return Object.entries(by).sort((a, b) => {
      if (groupBy === 'ct') return (parseInt(a[0].replace(/\D/g, '')) || 9999) - (parseInt(b[0].replace(/\D/g, '')) || 9999)
      return a[0].localeCompare(b[0])
    })
  }, [data, groupBy])

  if (loading && !data) return <div className="center-msg">lädt …</div>
  if (error && !data) return <div className="center-msg">Fehler: {String(error.message)}</div>

  const s = data?.summary || {}
  return (
    <>
      <div className="summary">
        <Stat k="Hosts" v={s.total ?? '—'} />
        <Stat k="Online" v={s.online ?? '—'} />
        <Stat k="Degraded" v={s.degraded ?? 0} />
        <Stat k="Offline" v={s.offline ?? 0} />
        <Stat k="Alarme" v={(data?.alerts || []).length} />
      </div>

      <div className="groupby">
        <span className="muted">Gruppieren:</span>
        {Object.entries(GROUPERS).map(([k, g]) => (
          <button key={k} className={`chip ${groupBy === k ? 'active' : ''}`} onClick={() => changeGroup(k)}>{g.label}</button>
        ))}
      </div>

      {groups.map(([cat, hosts]) => (
        <section key={cat}>
          <div className="group-title">{cat} · {hosts.length}</div>
          <div className="grid">
            {hosts.map(h => <HostCard key={h.key} h={h} />)}
          </div>
        </section>
      ))}
    </>
  )
}

function Stat({ k, v }) {
  return <div className="stat"><div className="k">{k}</div><div className="v">{v}</div></div>
}

function HostCard({ h }) {
  const m = h.metrics || {}
  return (
    <Link className="card" to={`/host/${encodeURIComponent(h.key)}`}>
      <div className="head">
        <StatusDot status={h.status} />
        <span className="name">{h.icon ? h.icon + ' ' : ''}{h.name}</span>
        <Pill status={h.status} />
      </div>
      <div className="ip">{h.ip || '—'}{h.ct_id ? ` · CT${h.ct_id}` : ''}</div>
      {h.os_name && <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>{h.os_name}</div>}
      <div style={{ marginTop: 10 }}>
        <MetricBar label="CPU" value={m.cpu} />
        <MetricBar label="RAM" value={m.ram} />
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        Services {h.svc_online ?? 0}/{h.svc_total ?? 0}
      </div>
    </Link>
  )
}
