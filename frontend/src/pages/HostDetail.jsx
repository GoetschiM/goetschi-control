import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { usePoll, getJSON, postJSON } from '../api.js'
import { Pill, StatusDot, MetricBar, Sparkline } from '../ui.jsx'

export default function HostDetail() {
  const { key } = useParams()
  const hostKey = decodeURIComponent(key)
  const { data } = usePoll('/api/live', 5000)
  const { data: agent } = usePoll(`/api/agent/${encodeURIComponent(hostKey)}`, 8000)
  const { data: procData } = usePoll(`/api/processes/${encodeURIComponent(hostKey)}`, 10000)
  const host = (data?.hosts || []).find(h => h.key === hostKey)

  const [cpuHist, setCpuHist] = useState([])
  const [ramHist, setRamHist] = useState([])
  const [logs, setLogs] = useState(null)
  const [busy, setBusy] = useState('')

  useEffect(() => {
    let alive = true
    const safe = (p) => getJSON(p).then(d => alive ? d : null).catch(() => null)
    safe(`/api/metrics/${encodeURIComponent(hostKey)}/history?metric=cpu`).then(d => alive && setCpuHist(normHist(d)))
    safe(`/api/metrics/${encodeURIComponent(hostKey)}/history?metric=ram`).then(d => alive && setRamHist(normHist(d)))
    safe(`/api/logs/${encodeURIComponent(hostKey)}`).then(d => alive && setLogs(normLogs(d)))
    return () => { alive = false }
  }, [hostKey])

  async function action(path, label) {
    if (!confirm(`${label}?`)) return
    setBusy(label)
    try { const r = await postJSON(path); alert(r?.ok === false ? `${label} fehlgeschlagen: ${r.error || r.msg}` : `${label}: ausgelöst`) }
    catch (e) { alert(`${label} fehlgeschlagen: ${e.message}`) }
    finally { setBusy('') }
  }

  if (!host) return <div className="center-msg">lädt Host …</div>
  const m = host.metrics || {}
  const a = host.agent || {}
  const containers = agent?.docker?.containers || []
  const procs = (procData?.procs || []).slice(0, 8)

  return (
    <>
      <div className="crumbs"><Link to="/">Übersicht</Link> / {host.name}</div>
      <div className="detail-head">
        <StatusDot status={host.status} />
        <span className="title">{host.icon ? host.icon + ' ' : ''}{host.name}</span>
        <Pill status={host.status} />
      </div>
      <div className="muted" style={{ marginBottom: 20, fontFamily: 'var(--mono)' }}>
        {host.ip}{host.ct_id ? ` · CT${host.ct_id}` : ''}{a.os ? ` · ${a.os}` : ''}
      </div>

      <div className="panels">
        <div className="panel">
          <h3>Auslastung</h3>
          <MetricBar label="CPU" value={m.cpu} source={host.ct_id ? 'proxmox' : 'agent'} />
          <Sparkline points={cpuHist} />
          <div style={{ height: 10 }} />
          <MetricBar label="RAM" value={m.ram} />
          <Sparkline points={ramHist} color="var(--ok)" />
          <div style={{ height: 10 }} />
          <MetricBar label="Disk" value={m.disk_pct} />
        </div>

        <div className="panel">
          <h3>Info</h3>
          <div className="kv"><span>Status</span><b>{host.status}</b></div>
          <div className="kv"><span>IP</span><span className="mono">{host.ip || '—'}</span></div>
          <div className="kv"><span>Container</span><span className="mono">{host.ct_id ? `CT${host.ct_id}` : '—'}</span></div>
          <div className="kv"><span>Ping</span><span className="mono">{host.ping_rtt != null ? `${host.ping_rtt} ms` : '—'}</span></div>
          <div className="kv"><span>Uptime</span><span className="mono">{a.uptime_h != null ? `${a.uptime_h} h` : '—'}</span></div>
          <div className="kv"><span>Agent</span><span className="mono">{a.agent_version || '—'}</span></div>
          <div className="kv"><span>OS</span><span className="mono">{a.os || '—'}</span></div>
        </div>

        <div className="panel">
          <h3>Docker · {containers.length}</h3>
          {containers.length === 0 && <div className="muted">{agent ? 'keine' : 'lädt …'}</div>}
          {containers.map((c, i) => {
            const up = (c.status || '').toLowerCase().startsWith('up') || (c.status || '').toLowerCase().includes('running')
            return (
              <Link className="svc-row" key={i} to={`/host/${encodeURIComponent(hostKey)}/c/${encodeURIComponent(c.name)}`}>
                <StatusDot status={up ? 'online' : 'offline'} />
                <span>{c.name}</span>
                <span className="port">{(c.image || '').split(':')[0].split('/').pop()}</span>
              </Link>
            )
          })}
        </div>

        <div className="panel">
          <h3>Services {host.svc_online ?? 0}/{host.svc_total ?? 0}</h3>
          {(host.services || []).length === 0 && <div className="muted">keine</div>}
          {(host.services || []).map((s, i) => (
            <div className="svc-row" key={i}>
              <StatusDot status={s.status} />
              {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a> : <span>{s.name}</span>}
              <span className="port">{s.port ? `:${s.port}` : ''}</span>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>Top-Prozesse</h3>
          {procs.length === 0 && <div className="muted">{procData ? '—' : 'lädt …'}</div>}
          {procs.map((p, i) => (
            <div className="svc-row" key={i}>
              <span className="mono" style={{ width: 46 }}>{p.cpu}%</span>
              <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.cmd}</span>
            </div>
          ))}
        </div>

        <div className="panel">
          <h3>Aktionen</h3>
          <div className="actions">
            <button className="btn" disabled={!!busy}
              onClick={() => action(`/api/agent/${encodeURIComponent(hostKey)}/restart`, 'Agent-Neustart')}>
              {busy === 'Agent-Neustart' ? '…' : '↻ Agent neustarten'}
            </button>
            <button className="btn" disabled={!!busy}
              onClick={() => action(`/api/restart/${encodeURIComponent(hostKey)}`, 'Host-Neustart')}>
              {busy === 'Host-Neustart' ? '…' : '⏻ Host neustarten'}
            </button>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
            Container-Aktionen (Neustart/Diagnose) auf der jeweiligen Container-Seite. SSH-Terminal & Update folgen.
          </p>
        </div>

        <div className="panel" style={{ gridColumn: '1 / -1' }}>
          <h3>Logs</h3>
          <div className="logs">
            {logs == null && <div className="muted">lädt …</div>}
            {Array.isArray(logs) && logs.length === 0 && <div className="muted">keine Logs</div>}
            {Array.isArray(logs) && logs.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </div>
      </div>
    </>
  )
}

function normHist(d) {
  if (!Array.isArray(d)) return []
  return d.map(p => (typeof p === 'number' ? p : (p.v ?? p.value ?? p.cpu ?? p.ram))).filter(v => v != null)
}

function normLogs(d) {
  if (!d) return []
  const arr = Array.isArray(d) ? d : (d.lines || d.logs || [])
  return arr.map(l => (typeof l === 'string' ? l : (l.msg || l.line || l.message || JSON.stringify(l)))).slice(0, 200)
}
