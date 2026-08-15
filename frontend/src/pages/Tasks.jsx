import { useEffect, useState } from 'react'
import { getJSON, postJSON, patchJSON, delJSON } from '../api.js'

const SCHEDULES = {
  manual: 'Manuell (nur auf Knopfdruck)',
  hourly: 'Stündlich',
  daily: 'Täglich',
  weekly: 'Wöchentlich',
  monthly: 'Monatlich',
}

const EXAMPLES = [
  { label: 'System-Updates (apt)', cmd: 'export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get upgrade -y && apt-get autoremove -y' },
  { label: 'Docker aufräumen', cmd: 'docker image prune -af && docker container prune -f' },
  { label: 'Speicherplatz prüfen', cmd: 'df -h /' },
  { label: 'Reboot', cmd: 'reboot' },
]

const blankForm = { name: '', command: '', mode: 'all', selected: [], schedule: 'monthly', enabled: true }

export default function Tasks() {
  const [tasks, setTasks] = useState([])
  const [targets, setTargets] = useState([])
  const [f, setF] = useState(blankForm)
  const [msg, setMsg] = useState('')
  const [open, setOpen] = useState({})

  async function load() { setTasks(await getJSON('/api/crons').catch(() => [])) }
  useEffect(() => {
    load(); getJSON('/api/crons/targets').then(setTargets).catch(() => {})
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])
  function flash(t) { setMsg(t); setTimeout(() => setMsg(''), 3000) }

  function toggleHost(k) {
    setF(s => ({ ...s, selected: s.selected.includes(k) ? s.selected.filter(x => x !== k) : [...s.selected, k] }))
  }

  async function create() {
    if (!f.name.trim()) return flash('Name fehlt')
    if (!f.command.trim()) return flash('Befehl fehlt')
    const tg = f.mode === 'all' ? ['all'] : f.selected
    if (!tg.length) return flash('Keine Ziel-Hosts gewählt')
    try {
      await postJSON('/api/crons', { name: f.name, command: f.command, targets: tg, schedule: f.schedule, enabled: f.enabled })
      flash('Aufgabe erstellt'); setF(blankForm); load()
    } catch (e) { flash('Fehler: ' + (e.message || e)) }
  }
  async function toggle(t) { await patchJSON(`/api/crons/${t.id}`, { enabled: !t.enabled }); load() }
  async function del(t) { if (confirm(`Aufgabe "${t.name}" löschen?`)) { await delJSON(`/api/crons/${t.id}`); load() } }
  async function run(t) {
    if (!confirm(`„${t.name}" jetzt auf ${t.targets.includes('all') ? 'allen Hosts' : t.targets.length + ' Host(s)'} ausführen?`)) return
    flash('Gestartet — Ergebnisse erscheinen in Kürze …')
    try { await postJSON(`/api/crons/${t.id}/run`); setTimeout(load, 4000) } catch (e) { flash('Fehler: ' + e.message) }
  }

  const allCats = [...new Set(targets.map(t => t.category))].sort()

  return (
    <>
      {msg && <div className="toast">{msg}</div>}

      <div className="group-title">Neue Aufgabe</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        <div style={{ display: 'grid', gap: 12, maxWidth: 760 }}>
          <input className="inp" placeholder="Name (z.B. Monatliche System-Updates)"
            value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />

          <div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Befehl (läuft via Proxmox <code>pct exec</code> als root)</div>
            <textarea className="inp" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 13 }}
              placeholder="apt-get update && apt-get upgrade -y"
              value={f.command} onChange={e => setF({ ...f, command: e.target.value })} />
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
              {EXAMPLES.map(ex => (
                <button key={ex.label} className="btn" style={{ fontSize: 11 }}
                  onClick={() => setF({ ...f, command: ex.cmd })}>＋ {ex.label}</button>
              ))}
            </div>
          </div>

          <div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Ziel-Hosts</div>
            <label style={{ marginRight: 16 }}>
              <input type="radio" checked={f.mode === 'all'} onChange={() => setF({ ...f, mode: 'all' })} /> Alle LXCs ({targets.length})
            </label>
            <label>
              <input type="radio" checked={f.mode === 'select'} onChange={() => setF({ ...f, mode: 'select' })} /> Auswahl
            </label>
            {f.mode === 'select' && (
              <div className="panel" style={{ marginTop: 8, maxHeight: 220, overflowY: 'auto' }}>
                {allCats.map(cat => (
                  <div key={cat} style={{ marginBottom: 6 }}>
                    <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase' }}>{cat || 'sonstige'}</div>
                    {targets.filter(t => t.category === cat).map(t => (
                      <label key={t.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 14, fontSize: 13 }}>
                        <input type="checkbox" checked={f.selected.includes(t.key)} onChange={() => toggleHost(t.key)} /> {t.name}
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="muted">Zeitplan</span>
            <select className="inp" value={f.schedule} onChange={e => setF({ ...f, schedule: e.target.value })}>
              {Object.entries(SCHEDULES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label style={{ marginLeft: 'auto' }}>
              <input type="checkbox" checked={f.enabled} onChange={e => setF({ ...f, enabled: e.target.checked })} /> aktiviert
            </label>
            <button className="btn primary" onClick={create}>+ Aufgabe erstellen</button>
          </div>
        </div>
      </div>

      <div className="group-title">Aufgaben · {tasks.length}</div>
      <div className="panel">
        {tasks.length === 0 && <div className="muted">Noch keine Aufgaben.</div>}
        {tasks.map(t => {
          const nHosts = t.targets.includes('all') ? 'alle' : t.targets.length
          const results = t.results || {}
          const isOpen = open[t.id]
          return (
            <div key={t.id} style={{ borderBottom: '1px solid var(--border,#222)', padding: '10px 0' }}>
              <div className="auto-row" style={{ gap: 8 }}>
                <input type="checkbox" className="chk" checked={!!t.enabled} onChange={() => toggle(t)} title="aktiviert" />
                <span className="auto-name">{t.name}</span>
                <span className="badge" style={{ fontSize: 11 }}>{SCHEDULES[t.schedule] || t.schedule}</span>
                <span className="muted" style={{ fontSize: 12 }}>· {nHosts} Host(s)</span>
                {t.last_run && (
                  <span className="muted" style={{ fontSize: 12 }}>
                    · zuletzt {new Date(t.last_run).toLocaleString()} ·{' '}
                    <b style={{ color: t.last_ok ? 'var(--ok,#4ade80)' : 'var(--bad,#f87171)' }}>{t.last_result || '—'}</b>
                  </span>
                )}
                <span style={{ flex: 1 }} />
                {Object.keys(results).length > 0 &&
                  <button className="btn" onClick={() => setOpen(o => ({ ...o, [t.id]: !o[t.id] }))}>{isOpen ? '▾' : '▸'} Ergebnisse</button>}
                <button className="btn primary" onClick={() => run(t)}>▶ Jetzt</button>
                <button className="btn danger" onClick={() => del(t)}>✕</button>
              </div>
              <div className="muted" style={{ fontSize: 12, fontFamily: 'monospace', marginLeft: 26, marginTop: 2 }}>$ {t.command}</div>
              {isOpen && (
                <div style={{ marginLeft: 26, marginTop: 8 }}>
                  {Object.entries(results).map(([hk, r]) => (
                    <div key={hk} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 12 }}>
                        <b style={{ color: r.ok ? 'var(--ok,#4ade80)' : 'var(--bad,#f87171)' }}>{r.ok ? '✓' : '✕'}</b> {hk}
                      </div>
                      <pre style={{ fontSize: 11, background: 'var(--bg2,#111)', padding: 8, borderRadius: 6, overflowX: 'auto', maxHeight: 220, margin: '2px 0' }}>{r.out || '(keine Ausgabe)'}</pre>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
        Aufgaben laufen über Proxmox <code>pct exec</code> als root im Ziel-LXC. Geplante Aufgaben werden alle 30 s geprüft.
        Bei <code>apt</code>-Updates <code>DEBIAN_FRONTEND=noninteractive</code> setzen, damit nichts auf Eingaben wartet.
        Befehle mit einfachen Anführungszeichen (<code>'</code>) werden derzeit nicht unterstützt.
      </p>
    </>
  )
}
