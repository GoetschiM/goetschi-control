import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getJSON, postJSON, patchJSON, delJSON } from '../api.js'
import { useConfirm } from './HostAdmin.jsx'

const AUTONOMY = {
  off: ['aus', 'Antigravity läuft nicht im Hintergrund.'],
  report: ['nur melden', 'Antigravity prüft und meldet, ändert aber nichts.'],
  full: ['voll (Root)', 'Antigravity handelt bei Prüfungen und Alarmen selbst. Jede Aktion wird protokolliert und gemeldet.'],
}
const ST = { ok: ['online', 'OK'], problem: ['degraded', 'Problem'], fixed: ['online', 'Behoben'], error: ['offline', 'Fehler'] }

function ago(ts) {
  if (!ts) return 'noch nie'
  const m = Math.round((Date.now() / 1000 - ts) / 60)
  return m < 1 ? 'gerade eben' : m < 60 ? `vor ${m} min` : m < 1440 ? `vor ${Math.round(m / 60)} h` : new Date(ts * 1000).toLocaleString()
}

// Wiederkehrende KI-Prüfungen (auch die von Antigravity angelegten), Alarm-Reaktionen und
// alle anderen geplanten Aufgaben dieses Servers an einem Ort.
export default function Monitors() {
  const [d, setD] = useState(null)
  const [open, setOpen] = useState(null)
  const [form, setForm] = useState({ name: '', prompt: '', interval_min: 60 })
  const [msg, setMsg] = useState('')
  const [ask, confirmEl] = useConfirm()
  const flash = t => { setMsg(t); setTimeout(() => setMsg(''), 3000) }

  async function load() { setD(await getJSON('/api/monitors').catch(() => null)) }
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t) }, [])

  async function add(e) {
    e.preventDefault()
    try { const r = await postJSON('/api/monitors', form); if (r.ok) { setForm({ name: '', prompt: '', interval_min: 60 }); flash('Prüfung angelegt'); load() } }
    catch (err) { flash('Fehler: ' + err.message) }
  }
  async function toggle(m) { await patchJSON(`/api/monitors/${m.id}`, { enabled: !m.enabled }); load() }
  async function runNow(m) {
    const r = await postJSON(`/api/monitors/${m.id}/run`).catch(e => ({ ok: false, error: e.message }))
    flash(r.ok ? `„${m.name}“ läuft – Ergebnis erscheint gleich hier` : r.error)
    setTimeout(load, 15000)
  }
  async function remove(m) {
    if (await ask({ title: `Prüfung „${m.name}“ löschen?`, text: 'Sie läuft danach nicht mehr.', ok: 'Löschen', danger: true })) {
      await delJSON(`/api/monitors/${m.id}`); load()
    }
  }

  if (!d) return <div className="center-msg">lädt …</div>
  const [aLabel, aText] = AUTONOMY[d.autonomy] || AUTONOMY.report
  const sys = d.system || {}
  const cronD = Object.entries(sys.cron_d || {})

  return (
    <>
      {msg && <div className="toast">{msg}</div>}
      {confirmEl}

      <div className={`setup ${d.autonomy === 'full' ? 'warn-box' : ''}`} style={{ marginBottom: 18 }}>
        <div className="setup-head" style={{ marginBottom: 0 }}>
          <div>
            <div className="setup-title">Selbstständigkeit: {aLabel}</div>
            <div className="muted">{aText} {!d.telegram && 'Telegram ist nicht eingerichtet – Meldungen erscheinen nur hier.'}</div>
          </div>
          <Link className="btn" to="/settings#integrationen">Ändern</Link>
        </div>
      </div>
      {!d.agy && <div className="panel muted" style={{ marginBottom: 18 }}>Antigravity (agy) ist auf diesem Server nicht installiert.</div>}

      <div className="group-title">Wiederkehrende Prüfungen · {d.monitors.length}</div>
      <div className="panel" style={{ marginBottom: 18 }}>
        {d.monitors.length === 0 && <div className="muted">Noch keine. Lege unten eine an oder bitte den KI-Assistenten darum.</div>}
        {d.monitors.map(m => {
          const [cls, lbl] = ST[m.last_status] || ['', '—']
          return (
            <div key={m.id} className="mon-row">
              <div className="mon-main" onClick={() => setOpen(open === m.id ? null : m.id)}>
                <span className={`pill ${m.enabled ? cls : 'stopped'}`}>{m.enabled ? lbl : 'pausiert'}</span>
                <b>{m.name}</b>
                <span className="muted small">alle {m.interval_min} min · zuletzt {ago(m.last_run)} · von {m.created_by === 'ki' ? 'KI' : m.created_by}</span>
              </div>
              <span className="row-actions">
                <button className="btn ghost" onClick={() => runNow(m)}>Jetzt</button>
                <button className={`switch ${m.enabled ? 'on' : ''}`} aria-pressed={m.enabled} title="aktiv" onClick={() => toggle(m)}><span /></button>
                <button className="icon-btn danger" title="Löschen" onClick={() => remove(m)}>🗑</button>
              </span>
              {open === m.id && (
                <div className="mon-detail">
                  <div className="muted small">Aufgabe</div>
                  <div className="msg-text" style={{ marginBottom: 10 }}>{m.prompt}</div>
                  <div className="muted small">Letztes Ergebnis</div>
                  <div className="msg-text">{m.last_result || '—'}</div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="group-title">Neue Prüfung</div>
      <form className="panel mon-form" onSubmit={add} style={{ marginBottom: 18 }}>
        <input id="mon-name" className="inp" placeholder="Name, z.B. Speicherplatz Dokploy" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
        <textarea id="mon-prompt" className="inp" rows={2} placeholder="Was soll geprüft werden? z.B. Prüfe, ob auf CT 100 die Disk über 85 % liegt und welche Docker-Images aufgeräumt werden können."
          value={form.prompt} onChange={e => setForm(f => ({ ...f, prompt: e.target.value }))} />
        <div className="actions">
          <label className="muted small" htmlFor="mon-int">alle</label>
          <input id="mon-int" className="inp" type="number" min={5} style={{ width: 90 }} value={form.interval_min} onChange={e => setForm(f => ({ ...f, interval_min: e.target.value }))} />
          <span className="muted small">Minuten</span>
          <button className="btn primary" disabled={!form.name.trim() || !form.prompt.trim()}>Anlegen</button>
        </div>
      </form>

      <div className="group-title">Letzte Läufe (Prüfungen und Alarm-Reaktionen)</div>
      <div className="panel" style={{ marginBottom: 18 }}>
        {d.runs.length === 0 && <div className="muted">Noch keine.</div>}
        {d.runs.map((r, i) => {
          const [cls, lbl] = ST[r.status] || ['', r.status]
          return (
            <details key={i} className="run-row">
              <summary>
                <span className={`pill ${cls}`}>{lbl}</span>
                <span className="tag">{r.kind === 'alert' ? 'Alarm' : 'Prüfung'}</span>
                {r.mode === 'full' && <span className="tag ok">hat gehandelt</span>}
                <span>{r.ref}</span>
                <span className="muted small" style={{ marginLeft: 'auto' }}>{ago(r.ts)}</span>
              </summary>
              <div className="msg-text mon-detail">{r.result}</div>
            </details>
          )
        })}
      </div>

      <div className="group-title">Weitere geplante Aufgaben auf diesem Server</div>
      <div className="panel">
        <div className="muted small" style={{ marginBottom: 8 }}>Alles, was ausserhalb des RRM geplant ist – auch Cron-Jobs, die jemand direkt anlegt.</div>
        <div className="muted small">crontab (root)</div>
        <pre className="logs">{sys.crontab_root || 'leer'}</pre>
        {cronD.map(([f, c]) => (<div key={f}><div className="muted small">/etc/cron.d/{f}</div><pre className="logs">{c}</pre></div>))}
        <div className="muted small">systemd-Timer</div>
        <pre className="logs">{sys.timers || '—'}</pre>
      </div>
    </>
  )
}
