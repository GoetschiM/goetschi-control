import { useMemo } from 'react'
import { usePoll } from '../api.js'

export default function Maintenance() {
  const { data: backups } = usePoll('/api/backups', 30000)
  const { data: ssl } = usePoll('/api/ssl', 60000)

  const jobs = backups?.jobs || []
  const lastOk = useMemo(() => {
    const oks = jobs.filter(j => j.ok).map(j => j.starttime)
    return oks.length ? Math.max(...oks) : (backups?.last_ok || null)
  }, [jobs, backups])

  const sslRows = useMemo(() => {
    const rows = []
    for (const [host, svcs] of Object.entries(ssl || {})) {
      for (const [svc, r] of Object.entries(svcs)) rows.push({ host, svc, ...r })
    }
    return rows.sort((a, b) => (a.days_left ?? 9999) - (b.days_left ?? 9999))
  }, [ssl])

  const backupStale = !lastOk || (Date.now() / 1000 - lastOk) > 2 * 86400

  return (
    <>
      <div className="group-title">Backups (Proxmox vzdump)</div>
      <div className="summary" style={{ marginBottom: 14 }}>
        <div className="stat" style={backupStale ? { borderColor: 'var(--crit)' } : {}}>
          <div className="k">Letztes erfolgreiches Backup</div>
          <div className="v" style={{ fontSize: 18, color: backupStale ? 'var(--crit)' : 'var(--ok)' }}>
            {lastOk ? new Date(lastOk * 1000).toLocaleString() : '⚠ keine'}
          </div>
        </div>
        <div className="stat">
          <div className="k">Jobs (letzte)</div>
          <div className="v">{jobs.length}</div>
        </div>
        <div className="stat">
          <div className="k">Fehlgeschlagen</div>
          <div className="v" style={{ color: jobs.some(j => !j.ok) ? 'var(--crit)' : 'var(--text)' }}>
            {jobs.filter(j => !j.ok).length}
          </div>
        </div>
      </div>
      {backupStale && (
        <div className="panel" style={{ borderColor: 'var(--crit)', color: 'var(--crit)', marginBottom: 14 }}>
          ⚠ Seit über 2 Tagen kein erfolgreiches Backup — bitte Backup-Storage/Job prüfen.
        </div>
      )}
      <div className="panel" style={{ marginBottom: 24 }}>
        {jobs.length === 0 && <div className="muted">keine Backup-Jobs gefunden</div>}
        {jobs.map((j, i) => (
          <div className="svc-row" key={i}>
            <span className={`dot-s s-${j.ok ? 'online' : 'offline'}`} />
            <span className="mono">{j.starttime ? new Date(j.starttime * 1000).toLocaleString() : '—'}</span>
            <span style={{ flex: 1, color: j.ok ? 'var(--text-dim)' : 'var(--crit)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {j.status}
            </span>
            <span className="port">{j.duration}</span>
          </div>
        ))}
      </div>

      <div className="group-title">SSL-Zertifikate</div>
      <div className="panel">
        {sslRows.length === 0 && <div className="muted">keine HTTPS-Dienste erfasst</div>}
        {sslRows.map((r, i) => {
          const d = r.days_left
          const col = d == null ? 'var(--text-mute)' : d < 15 ? 'var(--crit)' : d < 30 ? 'var(--warn)' : 'var(--ok)'
          return (
            <div className="svc-row" key={i}>
              <span className="dot-s" style={{ background: col }} />
              <span>{r.host} · {r.svc}</span>
              <span style={{ flex: 1 }} />
              {r.error
                ? <span className="muted">{r.error}</span>
                : <>
                    <span className="mono" style={{ color: col }}>{d != null ? `${d} Tage` : '—'}</span>
                    <span className="port">{r.expiry ? new Date(r.expiry * 1000).toLocaleDateString() : ''}</span>
                  </>}
            </div>
          )
        })}
      </div>
    </>
  )
}
