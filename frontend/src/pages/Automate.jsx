import { useEffect, useState } from 'react'
import { getJSON, postJSON, patchJSON, delJSON } from '../api.js'

const METRICS = { cpu: 'CPU %', ram: 'RAM %', disk: 'Disk %', status: 'Status' }
const ACTIONS = {
  telegram: 'Telegram-Nachricht',
  ai_diagnose: 'KI-Diagnose (→ Telegram/Log)',
  lxc_reboot: 'CT neustarten (Reboot)',
  restart_container: 'Docker-Container neustarten',
}

export default function Automate() {
  const [rules, setRules] = useState([])
  const [hosts, setHosts] = useState([])
  const [msg, setMsg] = useState('')
  const [f, setF] = useState({ name: '', scope_host: '', metric: 'cpu', op: '>', threshold: '90', action: 'telegram', action_arg: '', cooldown_min: 30 })

  async function load() {
    setRules(await getJSON('/api/automations').catch(() => []))
  }
  useEffect(() => { load(); getJSON('/api/live').then(d => setHosts(d?.hosts || [])).catch(() => {}) }, [])
  function flash(t) { setMsg(t); setTimeout(() => setMsg(''), 2500) }

  async function create() {
    if (!f.name.trim()) return flash('Name fehlt')
    try { await postJSON('/api/automations', f); flash('Regel erstellt'); setF({ ...f, name: '', action_arg: '' }); load() }
    catch (e) { flash('Fehler: ' + e.message) }
  }
  async function toggle(r) { await patchJSON(`/api/automations/${r.id}`, { enabled: !r.enabled }); load() }
  async function del(r) { if (confirm(`Regel "${r.name}" löschen?`)) { await delJSON(`/api/automations/${r.id}`); load() } }
  async function test(r) {
    flash('teste …')
    try { const res = await postJSON(`/api/automations/${r.id}/test`); flash(`Test (${res.host}): ${res.result}`) }
    catch (e) { flash('Fehler: ' + e.message) }
  }

  const isStatus = f.metric === 'status'

  return (
    <>
      {msg && <div className="toast">{msg}</div>}

      <div className="group-title">Neue Regel — „wenn X dann Y"</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        <div className="auto-form">
          <input className="inp" placeholder="Name (z.B. CPU-Alarm Nova)" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />
          <select className="inp" value={f.scope_host} onChange={e => setF({ ...f, scope_host: e.target.value })}>
            <option value="">alle Hosts</option>
            {hosts.map(h => <option key={h.key} value={h.key}>{h.name}</option>)}
          </select>
          <span className="muted">wenn</span>
          <select className="inp" value={f.metric} onChange={e => setF({ ...f, metric: e.target.value, op: e.target.value === 'status' ? '==' : '>', threshold: e.target.value === 'status' ? 'offline' : '90' })}>
            {Object.entries(METRICS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {isStatus ? (
            <select className="inp" value={f.threshold} onChange={e => setF({ ...f, threshold: e.target.value })}>
              <option value="offline">offline</option>
              <option value="degraded">degraded</option>
              <option value="online">online</option>
            </select>
          ) : (
            <>
              <select className="inp" style={{ width: 60 }} value={f.op} onChange={e => setF({ ...f, op: e.target.value })}>
                <option value=">">&gt;</option><option value="<">&lt;</option>
              </select>
              <input className="inp" style={{ width: 70 }} value={f.threshold} onChange={e => setF({ ...f, threshold: e.target.value })} />
            </>
          )}
          <span className="muted">dann</span>
          <select className="inp" value={f.action} onChange={e => setF({ ...f, action: e.target.value })}>
            {Object.entries(ACTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {(f.action === 'restart_container' || f.action === 'telegram') && (
            <input className="inp" placeholder={f.action === 'restart_container' ? 'Container-Name' : 'Nachricht (optional)'}
              value={f.action_arg} onChange={e => setF({ ...f, action_arg: e.target.value })} />
          )}
          <span className="muted">Cooldown</span>
          <input className="inp" style={{ width: 60 }} type="number" value={f.cooldown_min} onChange={e => setF({ ...f, cooldown_min: e.target.value })} />
          <span className="muted">min</span>
          <button className="btn primary" onClick={create}>+ Erstellen</button>
        </div>
      </div>

      <div className="group-title">Regeln · {rules.length}</div>
      <div className="panel">
        {rules.length === 0 && <div className="muted">Noch keine Automationen.</div>}
        {rules.map(r => (
          <div className="auto-row" key={r.id}>
            <input type="checkbox" className="chk" checked={!!r.enabled} onChange={() => toggle(r)} />
            <span className="auto-name">{r.name}</span>
            <span className="muted" style={{ flex: 1, fontSize: 12 }}>
              {r.scope_host || 'alle'} · wenn {METRICS[r.metric]} {r.op} {r.threshold} → {ACTIONS[r.action]}{r.action_arg ? ` (${r.action_arg})` : ''}
              {r.last_fired ? ` · zuletzt ${new Date(r.last_fired * 1000).toLocaleString()}` : ''}
            </span>
            <button className="btn" onClick={() => test(r)}>Test</button>
            <button className="btn danger" onClick={() => del(r)}>✕</button>
          </div>
        ))}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
        Regeln werden alle 60 s gegen die Live-Daten geprüft. Telegram-Aktionen brauchen einen konfigurierten Telegram-Token.
      </p>
    </>
  )
}
