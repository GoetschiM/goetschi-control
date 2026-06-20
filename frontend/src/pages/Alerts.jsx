import { useNavigate } from 'react-router-dom'
import { usePoll } from '../api.js'

export default function Alerts() {
  const { data, loading } = usePoll('/api/alerts', 5000)
  const navigate = useNavigate()
  const alerts = Array.isArray(data) ? data : (data?.alerts || [])

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
        </div>
      ))}
    </div>
  )
}
