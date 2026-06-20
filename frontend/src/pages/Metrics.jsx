import { useEffect, useState } from 'react'
import { getJSON, usePoll } from '../api.js'
import { MetricChart } from '../ui.jsx'

const GRAFANA_URL = 'http://10.0.60.110:3000'

export default function Metrics() {
  const { data: live } = usePoll('/api/live', 8000)
  const hosts = live?.hosts || []
  const [hostKey, setHostKey] = useState('')
  const [hist, setHist] = useState({ cpu: [], ram: [], disk: [] })

  useEffect(() => { if (!hostKey && hosts.length) setHostKey(hosts.find(h => h.ct_id)?.key || hosts[0].key) }, [hosts, hostKey])

  useEffect(() => {
    if (!hostKey) return
    let alive = true
    const get = m => getJSON(`/api/metrics/${encodeURIComponent(hostKey)}/history?metric=${m}`).catch(() => [])
    Promise.all([get('cpu'), get('ram'), get('disk')]).then(([cpu, ram, disk]) => {
      if (alive) setHist({ cpu: norm(cpu), ram: norm(ram), disk: norm(disk) })
    })
    const t = setInterval(() => {
      Promise.all([get('cpu'), get('ram'), get('disk')]).then(([cpu, ram, disk]) => alive && setHist({ cpu: norm(cpu), ram: norm(ram), disk: norm(disk) }))
    }, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [hostKey])

  const topCpu = [...hosts].filter(h => h.metrics?.cpu != null).sort((a, b) => b.metrics.cpu - a.metrics.cpu).slice(0, 6)
  const topRam = [...hosts].filter(h => h.metrics?.ram != null).sort((a, b) => b.metrics.ram - a.metrics.ram).slice(0, 6)

  return (
    <>
      <div className="ai-bar" style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16 }}>
        <select className="inp" value={hostKey} onChange={e => setHostKey(e.target.value)}>
          {hosts.map(h => <option key={h.key} value={h.key}>{h.name}</option>)}
        </select>
        <a className="btn" href={GRAFANA_URL} target="_blank" rel="noreferrer">📊 In Grafana öffnen</a>
      </div>

      <div className="charts">
        <MetricChart points={hist.cpu} color="var(--accent)" label="CPU" />
        <MetricChart points={hist.ram} color="var(--ok)" label="RAM" />
        <MetricChart points={hist.disk} color="var(--warn)" label="Disk" />
      </div>

      <div className="group-title" style={{ marginTop: 26 }}>Aktuelle Top-Last</div>
      <div className="panels">
        <TopList title="CPU" hosts={topCpu} metric="cpu" />
        <TopList title="RAM" hosts={topRam} metric="ram" />
      </div>
    </>
  )
}

function TopList({ title, hosts, metric }) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      {hosts.map(h => (
        <div className="metric" key={h.key}>
          <div className="lbl"><span>{h.name}</span><b>{h.metrics[metric]}%</b></div>
          <div className={`bar ${h.metrics[metric] >= 90 ? 'crit' : h.metrics[metric] >= 75 ? 'warn' : ''}`}>
            <span style={{ width: `${Math.min(100, h.metrics[metric])}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function norm(d) {
  if (!Array.isArray(d)) return []
  return d.map(p => (typeof p === 'number' ? p : (p.v ?? p.value))).filter(v => v != null)
}
