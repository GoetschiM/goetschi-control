import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { usePoll, getJSON, postJSON } from '../api.js'
import { StatusDot } from '../ui.jsx'

export default function ContainerDetail() {
  const { key, name } = useParams()
  const hostKey = decodeURIComponent(key)
  const cname = decodeURIComponent(name)
  const { data } = usePoll(`/api/agent/${encodeURIComponent(hostKey)}`, 8000)

  const [diag, setDiag] = useState(null)
  const [diagBusy, setDiagBusy] = useState(false)
  const [busy, setBusy] = useState(false)

  const containers = data?.docker?.containers || []
  const c = containers.find(x => x.name === cname)
  const isUp = (c?.status || '').toLowerCase().startsWith('up') || (c?.status || '').toLowerCase().includes('running')
  const source = c?.source === 'systemd' ? 'systemd' : 'docker'

  async function runDiag() {
    setDiagBusy(true); setDiag(null)
    try {
      const d = await getJSON(`/api/nanoclaw/diagnose/${encodeURIComponent(hostKey)}/${encodeURIComponent(cname)}?source=${source}`)
      setDiag(d)
    } catch (e) { setDiag({ ok: false, advice: e.message }) }
    finally { setDiagBusy(false) }
  }

  async function act(action) {
    const labels = { start: 'starten', stop: 'stoppen', restart: 'neustarten' }
    if (!confirm(`Container "${cname}" ${labels[action]}?`)) return
    setBusy(true)
    try {
      const r = await postJSON(`/api/container/${encodeURIComponent(hostKey)}/${action}`, { name: cname })
      alert(r.ok ? `${labels[action]}: ${r.msg || 'ok'}` : `Fehler: ${r.error || r.msg || 'unbekannt'}`)
    } catch (e) { alert(`Fehler: ${e.message}`) }
    finally { setBusy(false) }
  }

  return (
    <>
      <div className="crumbs">
        <Link to="/">Übersicht</Link> / <Link to={`/host/${encodeURIComponent(hostKey)}`}>{hostKey}</Link> / {cname}
      </div>
      <div className="detail-head">
        <StatusDot status={isUp ? 'online' : 'offline'} />
        <span className="title">{cname}</span>
        <span className={`pill ${isUp ? 'online' : 'offline'}`}>{isUp ? 'running' : 'stopped'}</span>
      </div>

      {!c && <div className="muted" style={{ marginBottom: 16 }}>Container nicht in der Agent-Liste — evtl. gestoppt/entfernt.</div>}

      <div className="panels">
        <div className="panel">
          <h3>Container</h3>
          <div className="kv"><span>Name</span><span className="mono">{cname}</span></div>
          <div className="kv"><span>Image</span><span className="mono">{c?.image || '—'}</span></div>
          <div className="kv"><span>Status</span><span className="mono">{c?.status || '—'}</span></div>
          <div className="kv"><span>Ports</span><span className="mono">{c?.ports || '—'}</span></div>
          <div className="kv"><span>Quelle</span><span className="mono">{c?.source || 'docker'}</span></div>
          <div className="kv"><span>ID</span><span className="mono">{c?.id || '—'}</span></div>
        </div>

        <div className="panel">
          <h3>Aktionen</h3>
          <div className="actions">
            {!isUp && <button className="btn" disabled={busy} onClick={() => act('start')}>{busy ? '…' : '▶ Start'}</button>}
            {isUp && <button className="btn" disabled={busy} onClick={() => act('stop')}>{busy ? '…' : '⏹ Stop'}</button>}
            <button className="btn" disabled={busy} onClick={() => act('restart')}>{busy ? '…' : '↻ Neustart'}</button>
            <button className="btn" disabled={diagBusy} onClick={runDiag}>{diagBusy ? 'analysiere …' : '🩺 Diagnose'}</button>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
            Diagnose nutzt den gl-Agent (kein SSH) — liest Logs und erkennt die Fehlerursache.
          </p>
        </div>

        {diag && (
          <div className="panel" style={{ gridColumn: '1 / -1' }}>
            <h3>Diagnose {diag.source ? `· ${diag.source}` : ''}</h3>
            {diag.ok === false
              ? <div style={{ color: 'var(--crit)' }}>{diag.advice}</div>
              : <>
                  <div className="kv"><span>Befund</span><b>{diag.label}</b></div>
                  <div className="kv"><span>Empfehlung</span><span>{diag.advice || '—'}</span></div>
                  <h3 style={{ marginTop: 16 }}>Logs</h3>
                  <div className="logs">{(diag.logs || '').split('\n').map((l, i) => <div key={i}>{l}</div>)}</div>
                </>}
          </div>
        )}
      </div>
    </>
  )
}
