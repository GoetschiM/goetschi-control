import { useEffect, useState } from 'react'
import { getJSON, postJSON, delJSON } from '../api.js'

const INTEGRATIONS = [
  ['proxmox', 'Proxmox', 'PROXMOX_HOST + PROXMOX_TOKEN: erkennt alle Container automatisch'],
  ['unifi', 'UniFi', 'UNIFI_URL + UNIFI_USER + UNIFI_PASS: Netzwerk, Clients, WAN'],
  ['prometheus', 'Prometheus', 'PROMETHEUS_URL: Metrik-Verlauf (optional)'],
  ['loki', 'Loki', 'LOKI_URL: zentrale Logs (optional)'],
  ['dokploy', 'Dokploy', 'DOKPLOY_URL + DOKPLOY_API_KEY: Apps und Redeploy'],
  ['coolify', 'Coolify', 'COOLIFY_URL + COOLIFY_API_KEY: Apps und Redeploy'],
  ['litellm', 'LiteLLM', 'LITELLM_URL + LITELLM_KEY: KI-Analyse'],
  ['telegram', 'Telegram', 'TELEGRAM_TOKEN + TELEGRAM_CHAT_ID: Alarme aufs Handy'],
]

function Copy({ text }) {
  const [ok, setOk] = useState(false)
  return (
    <button className="btn" onClick={() => {
      navigator.clipboard?.writeText(text).then(() => { setOk(true); setTimeout(() => setOk(false), 1500) }).catch(() => {})
    }}>{ok ? 'kopiert' : 'Kopieren'}</button>
  )
}

function Cmd({ label, text }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div className="muted" style={{ marginBottom: 6 }}>{label}</div>
      <div className="actions" style={{ alignItems: 'flex-start' }}>
        <pre className="logs mono" style={{ flex: 1, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', minWidth: 240 }}>{text}</pre>
        <Copy text={text} />
      </div>
    </div>
  )
}

export default function Connect() {
  const [c, setC] = useState(null)
  const [hosts, setHosts] = useState([])
  const [name, setName] = useState('')
  const [ip, setIp] = useState('')
  const [cidr, setCidr] = useState('')
  const [scan, setScan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const flash = t => { setMsg(t); setTimeout(() => setMsg(''), 3000) }
  async function load() {
    setC(await getJSON('/api/connect').catch(() => null))
    const live = await getJSON('/api/live').catch(() => null)
    setHosts((live?.hosts || []).filter(h => h.key.startsWith('host-')))
  }
  useEffect(() => {
    load()
    getJSON('/api/scan').then(d => setCidr(d.default_cidr)).catch(() => {})
  }, [])

  async function addHost(n, addr) {
    try {
      const r = await postJSON('/api/hosts', { name: n, ip: addr })
      if (r.ok) { flash(`${n || addr} hinzugefügt`); setName(''); setIp(''); load()
        setScan(s => s && { ...s, hosts: s.hosts.map(h => h.ip === addr ? { ...h, known: true } : h) }) }
    } catch (e) { flash('Fehler: ' + e.message) }
  }
  async function removeHost(key) {
    await delJSON(`/api/hosts/${encodeURIComponent(key)}`).catch(() => {}); load()
  }
  async function runScan() {
    setBusy(true); setScan(null)
    try { setScan(await postJSON('/api/scan', { cidr })) }
    catch (e) { flash('Scan fehlgeschlagen: ' + e.message) }
    finally { setBusy(false) }
  }

  if (!c) return <div className="muted">lädt …</div>
  return (
    <>
      {msg && <div className="toast">{msg}</div>}

      <div className="group-title">1 · Agent auf einem Host installieren</div>
      <div className="panel">
        <div className="muted" style={{ marginBottom: 12 }}>
          Auf dem Zielhost als root ausführen (benötigt nur Python 3 und curl). Der Host meldet sich danach von selbst
          und erscheint in Übersicht, Metriken und Inventar.
        </div>
        <Cmd label="Installationsbefehl" text={c.install_cmd} />
      </div>

      <div className="group-title">2 · Hosts ohne Agent hinzufügen</div>
      <div className="panel">
        <div className="actions" style={{ marginBottom: 14 }}>
          <input className="inp" placeholder="Name" value={name} onChange={e => setName(e.target.value)} />
          <input className="inp" placeholder="IP-Adresse" value={ip} onChange={e => setIp(e.target.value)} />
          <button className="btn" disabled={!ip.trim()} onClick={() => addHost(name.trim(), ip.trim())}>Hinzufügen</button>
        </div>
        <div className="actions" style={{ marginBottom: 10 }}>
          <input className="inp" style={{ width: 200 }} placeholder="Netz, z.B. 192.168.1.0/24" value={cidr} onChange={e => setCidr(e.target.value)} />
          <button className="btn" disabled={busy} onClick={runScan}>{busy ? 'scannt …' : 'Netzwerk scannen'}</button>
        </div>
        {scan && (
          <div style={{ marginTop: 10 }}>
            <div className="muted" style={{ marginBottom: 6 }}>{scan.hosts.length} Hosts in {scan.cidr} erreichbar</div>
            {scan.hosts.map(h => (
              <div className="kv" key={h.ip}>
                <span className="mono">{h.ip}</span>
                <span>{h.name || '—'}</span>
                <span className="mono muted">{h.ports.join(' ') || 'keine bekannten Ports'}</span>
                {h.known
                  ? <span className="muted">bereits erfasst</span>
                  : <button className="btn" onClick={() => addHost(h.name.split('.')[0], h.ip)}>Hinzufügen</button>}
              </div>
            ))}
          </div>
        )}
        {hosts.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="muted" style={{ marginBottom: 6 }}>Manuell hinzugefügt</div>
            {hosts.map(h => (
              <div className="kv" key={h.key}>
                <span>{h.name}</span><span className="mono">{h.ip}</span>
                <button className="btn" onClick={() => removeHost(h.key)}>Entfernen</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="group-title">3 · Integrationen</div>
      <div className="panel">
        <div className="muted" style={{ marginBottom: 10 }}>
          Werte in der Umgebung des Dashboards setzen (Docker-Env oder <span className="mono">.env</span>) und neu starten.
          Jede Integration ist optional.
        </div>
        {INTEGRATIONS.map(([k, n, how]) => (
          <div className="kv" key={k}>
            <span>{c.integrations[k] ? '●' : '○'} {n}</span>
            <span className="muted">{how}</span>
            <span className="muted">{c.integrations[k] ? 'verbunden' : 'nicht konfiguriert'}</span>
          </div>
        ))}
      </div>

      <div className="group-title">4 · Andere Agenten anbinden (MCP)</div>
      <div className="panel">
        <div className="muted" style={{ marginBottom: 12 }}>
          Nur lesend. Werkzeuge: list_containers, infra_status, list_agents, active_alerts, find_package.
        </div>
        <Cmd label="MCP-URL" text={c.mcp_url} />
        <Cmd label="Claude Code" text={c.mcp_cmd} />
        <Cmd label="Bearer-Token" text={c.mcp_token} />
      </div>
    </>
  )
}
