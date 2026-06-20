import { useEffect, useState } from 'react'
import { getJSON } from '../api.js'

export default function Integrations() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    setItems(await getJSON('/api/integrations').catch(() => []))
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const okN = items.filter(i => i.ok).length

  return (
    <>
      <div className="actions" style={{ marginBottom: 16 }}>
        <span className="muted">{okN}/{items.length} Integrationen ok</span>
        <button className="btn" onClick={load} disabled={loading}>{loading ? 'prüfe …' : '⟲ Neu prüfen'}</button>
      </div>
      <div className="panel">
        {loading && items.length === 0 && <div className="muted">prüfe Datenquellen …</div>}
        {items.map((i, idx) => (
          <div className="svc-row" key={idx}>
            <span className={`dot-s s-${i.ok ? 'online' : 'offline'}`} />
            <span style={{ fontWeight: 600, width: 200 }}>{i.name}</span>
            <span className={i.ok ? 'role-admin' : 'role-viewer'} style={{ width: 60 }}>{i.ok ? 'OK' : 'FEHLER'}</span>
            <span className="muted" style={{ flex: 1 }}>{i.detail}</span>
          </div>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
        Live-Selbsttest aller angebundenen Systeme. „Loki leer" und „Dokploy kein Token" sind bekannte offene Punkte.
      </p>
    </>
  )
}
