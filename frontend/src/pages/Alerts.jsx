import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePoll, postJSON } from '../api.js'

export default function Alerts() {
  const { data, loading, refresh } = usePoll('/api/alerts', 5000)
  const navigate = useNavigate()
  const [acked, setAcked] = useState(() => new Set())

  const all = Array.isArray(data) ? data : (data?.alerts || [])
  const alerts = all.filter(a => !a.acked && !acked.has(sig(a)))

  async function ack(a, e) {
    e.stopPropagation()
    const s = sig(a)
    setAcked(prev => new Set(prev).add(s))
    try { await postJSON('/api/alerts/ack', { sig: s }) } catch {}
    setTimeout(refresh, 500)
  }

  if (loading && !data) return <div className="center-msg">lädt …</div>
  if (alerts.length === 0) return <div className="center-msg">Keine aktiven Alarme ✓</div>

  return (
    <div className="alert-list">
      {alerts.map((a, i) => (
        <div key={i} className={`alert sev-${a.severity || 'warn'}`}
          onClick={() => a.key && navigate(`/host/${encodeURIComponent(a.key)}`)}
          style={{ cursor: a.key ? 'pointer' : 'default' }}>
          <span className={`sev-dot sev-${a.severity || 'warn'}`} />
          <div className="a-body">
            <div className="a-msg">{a.msg || a.message}</div>
            <div className="a-meta">{a.host || a.key || ''}{a.ip ? ` · ${a.ip}` : ''}</div>
          </div>
          <span className="a-sev">{a.severity || 'warn'}</span>
          <button className="btn" onClick={(e) => ack(a, e)} title="Als gelesen markieren">✓</button>
        </div>
      ))}
    </div>
  )
}

function sig(a) { return `${a.key}|${a.msg || a.message}` }
