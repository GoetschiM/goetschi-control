import { useEffect, useState } from 'react'
import { getJSON } from '../api.js'

export default function Grafana() {
  const [data, setData] = useState(null)
  const [sel, setSel] = useState('')

  useEffect(() => {
    getJSON('/api/grafana/dashboards').then(d => {
      setData(d)
      if (d?.dashboards?.length) setSel(d.dashboards[0].url)
    }).catch(() => setData({ dashboards: [], error: 'nicht erreichbar' }))
  }, [])

  if (!data) return <div className="center-msg">lädt …</div>
  const base = data.base || ''
  const dbs = data.dashboards || []
  const src = sel ? `${base}${sel}?orgId=1&kiosk&theme=dark&refresh=30s` : ''

  return (
    <>
      <div className="ai-bar" style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 14 }}>
        <select className="inp" value={sel} onChange={e => setSel(e.target.value)} style={{ minWidth: 240 }}>
          {dbs.map(d => <option key={d.uid} value={d.url}>{d.title}</option>)}
        </select>
        <a className="btn" href={base} target="_blank" rel="noreferrer">↗ In Grafana öffnen</a>
        {dbs.length === 0 && <span className="muted">Keine Dashboards{data.error ? ` (${data.error})` : ''}</span>}
      </div>
      {src && <iframe className="grafana-frame" src={src} title="Grafana" />}
    </>
  )
}
