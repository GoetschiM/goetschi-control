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

  const conf = items.filter(i => i.state !== 'off')
  const okN = conf.filter(i => i.ok).length

  return (
    <>
      <div className="actions" style={{ marginBottom: 16 }}>
        <span className="muted">{okN} von {conf.length} eingerichteten Integrationen ok · {items.length - conf.length} nicht eingerichtet</span>
        <button className="btn" onClick={load} disabled={loading}>{loading ? 'prüfe …' : '⟲ Neu prüfen'}</button>
      </div>
      <div className="panel">
        {loading && items.length === 0 && <div className="muted">prüfe Datenquellen …</div>}
        {items.map((i, idx) => (
          <div className="svc-row" key={idx}>
            <span className={`dot-s ${i.state === 'off' ? 's-off' : `s-${i.ok ? 'online' : 'offline'}`}`} />
            <span style={{ fontWeight: 600, width: 260 }}>{i.name}</span>
            <span className={`int-state ${i.state || (i.ok ? 'ok' : 'error')}`}>{i.state === 'off' ? 'nicht eingerichtet' : i.ok ? 'OK' : 'Fehler'}</span>
            <span className="muted" style={{ flex: 1 }}>{i.state === 'off' ? i.how : i.detail}</span>
          </div>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
        Live-Selbsttest aller angebundenen Systeme. Nicht konfigurierte Integrationen richtest du unter „Hosts & Agenten" ein.
      </p>
    </>
  )
}
