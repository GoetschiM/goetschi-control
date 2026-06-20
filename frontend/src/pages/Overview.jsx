import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { usePoll } from '../api.js'
import { Pill, StatusDot, MetricBar } from '../ui.jsx'

export default function Overview() {
  const { data, loading, error } = usePoll('/api/live', 5000)

  const groups = useMemo(() => {
    const hosts = data?.hosts || []
    const by = {}
    for (const h of hosts) {
      const c = h.category || 'sonstige'
      ;(by[c] ||= []).push(h)
    }
    return Object.entries(by).sort((a, b) => a[0].localeCompare(b[0]))
  }, [data])

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
