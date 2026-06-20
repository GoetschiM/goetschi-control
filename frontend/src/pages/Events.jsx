import { useEffect, useMemo, useState } from 'react'
import { getJSON } from '../api.js'

function toEpoch(ts) {
  if (typeof ts === 'number') return ts
  if (typeof ts === 'string') { const p = Date.parse(ts); return isNaN(p) ? 0 : Math.floor(p / 1000) }
  return 0
}

export default function Events() {
  const [nc, setNc] = useState([])
  const [audit, setAudit] = useState([])
  const [filter, setFilter] = useState('all')

  async function load() {
    const [a, b] = await Promise.all([
      getJSON('/api/nanoclaw/events').catch(() => []),
      getJSON('/api/audit').catch(() => []),
    ])
    setNc(Array.isArray(a) ? a : [])
    setAudit(Array.isArray(b) ? b : [])
  }
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [])

  const items = useMemo(() => {
    const ev = nc.map(e => ({
      ts: toEpoch(e.ts), kind: e.action === 'automation' ? 'automation' : 'engine',
      sev: e.severity || 'info', host: e.host, action: e.action,
      text: `${e.detail || ''}${e.result ? ' → ' + e.result : ''}`,
    }))
    const au = audit.map(a => ({
      ts: toEpoch(a.ts), kind: 'audit', sev: 'info', host: a.host,
      action: a.action, text: `${a.user || ''} · ${a.detail || ''}`,
    }))
    let all = [...ev, ...au].sort((x, y) => (y.ts || 0) - (x.ts || 0))
    if (filter !== 'all') all = all.filter(i => i.kind === filter)
    return all.slice(0, 300)
  }, [nc, audit, filter])

  const TABS = { all: 'Alle', automation: 'Automationen', engine: 'Self-Healing', audit: 'Audit' }

  return (
    <>
      <div className="groupby">
        {Object.entries(TABS).map(([k, v]) => (
          <button key={k} className={`chip ${filter === k ? 'active' : ''}`} onClick={() => setFilter(k)}>{v}</button>
        ))}
      </div>

      <div className="panel">
        {items.length === 0 && <div className="muted">Keine Ereignisse.</div>}
        {items.map((i, idx) => (
          <div className="ev-row" key={idx}>
            <span className={`ev-kind k-${i.kind}`}>{i.kind}</span>
            <span className="ev-time mono">{i.ts ? new Date(i.ts * 1000).toLocaleString() : ''}</span>
            <span className={`dot-s s-${i.sev === 'warn' ? 'degraded' : i.sev === 'critical' ? 'offline' : 'online'}`} />
            <span className="ev-host">{i.host || ''}</span>
            <span className="ev-action mono">{i.action}</span>
            <span className="ev-text muted">{i.text}</span>
          </div>
        ))}
      </div>
    </>
  )
}
