import { useEffect, useState } from 'react'
import { getJSON, postJSON } from '../api.js'

// Ad-hoc Befehle sofort auf mehreren Hosts ausführen und Ausgaben gesammelt anzeigen.
const EXAMPLES = [
  { label: 'IP-Adressen', cmd: 'ip -4 addr show eth0 | grep inet' },
  { label: 'Uptime / Last', cmd: 'uptime' },
  { label: 'Speicherplatz', cmd: 'df -h /' },
  { label: 'RAM', cmd: 'free -m' },
  { label: 'OS-Version', cmd: 'cat /etc/os-release | grep PRETTY_NAME' },
  { label: 'Fehlerhafte Dienste', cmd: 'systemctl --failed --no-legend --no-pager' },
  { label: 'Docker-Container', cmd: 'docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo kein-docker' },
  { label: 'apt Updates verfügbar', cmd: 'apt-get -s upgrade 2>/dev/null | grep -c ^Inst' },
]

export default function Ansible() {
  const [targets, setTargets] = useState([])
  const [cmd, setCmd] = useState('')
  const [mode, setMode] = useState('select')   // 'all' | 'select'
  const [selected, setSelected] = useState([])
  const [running, setRunning] = useState(false)
  const [res, setRes] = useState(null)
  const [msg, setMsg] = useState('')

  useEffect(() => { getJSON('/api/crons/targets').then(setTargets).catch(() => {}) }, [])
  function flash(t) { setMsg(t); setTimeout(() => setMsg(''), 3500) }

  function toggleHost(k) {
    setSelected(s => s.includes(k) ? s.filter(x => x !== k) : [...s, k])
  }
  const allCats = [...new Set(targets.map(t => t.category))].sort()

  async function runNow() {
    if (!cmd.trim()) return flash('Befehl fehlt')
    const tg = mode === 'all' ? ['all'] : selected
    if (!tg.length) return flash('Keine Ziel-Hosts gewählt')
    setRunning(true); setRes(null)
    try {
      const r = await postJSON('/api/exec', { command: cmd, targets: tg })
      setRes(r)
    } catch (e) {
      flash('Fehler: ' + (e.message || e))
    } finally {
      setRunning(false)
    }
  }

  const nameOf = k => (targets.find(t => t.key === k) || {}).name || k

  return (
    <>
      {msg && <div className="toast">{msg}</div>}

      <div className="group-title">Befehl ausführen (Ad-hoc, alle Hosts auf einmal)</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        <div style={{ display: 'grid', gap: 12, maxWidth: 820 }}>
          <div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
              Befehl (läuft via Proxmox <code>pct exec</code> als root im Ziel-LXC)
            </div>
            <textarea className="inp" rows={2} style={{ width: '100%', fontFamily: 'monospace', fontSize: 13 }}
              placeholder="z.B. ip a  ·  uptime  ·  df -h"
              value={cmd} onChange={e => setCmd(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) runNow() }} />
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
              {EXAMPLES.map(ex => (
                <button key={ex.label} className="btn" style={{ fontSize: 11 }}
                  onClick={() => setCmd(ex.cmd)}>＋ {ex.label}</button>
              ))}
            </div>
          </div>

          <div>
            <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Ziel-Hosts</div>
            <label style={{ marginRight: 16 }}>
              <input type="radio" checked={mode === 'all'} onChange={() => setMode('all')} /> Alle LXCs ({targets.length})
            </label>
            <label style={{ marginRight: 16 }}>
              <input type="radio" checked={mode === 'select'} onChange={() => setMode('select')} /> Auswahl ({selected.length})
            </label>
            {mode === 'select' && (
              <div className="panel" style={{ marginTop: 8, maxHeight: 240, overflowY: 'auto' }}>
                <div style={{ marginBottom: 6 }}>
                  <button className="btn" style={{ fontSize: 11 }} onClick={() => setSelected(targets.map(t => t.key))}>Alle wählen</button>{' '}
                  <button className="btn" style={{ fontSize: 11 }} onClick={() => setSelected([])}>Keine</button>
                </div>
                {allCats.map(cat => (
                  <div key={cat} style={{ marginBottom: 6 }}>
                    <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase' }}>{cat || 'sonstige'}</div>
                    {targets.filter(t => t.category === cat).map(t => (
                      <label key={t.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 14, fontSize: 13 }}>
                        <input type="checkbox" checked={selected.includes(t.key)} onChange={() => toggleHost(t.key)} /> {t.name}
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button className="btn primary" onClick={runNow} disabled={running}>
              {running ? '… läuft' : '▶ Auf allen ausführen'}
            </button>
            <span className="muted" style={{ fontSize: 12 }}>Strg/Cmd + Enter</span>
            {res && <span className="badge" style={{ marginLeft: 'auto' }}>{res.summary}</span>}
          </div>
        </div>
      </div>

      {running && <div className="panel muted">Führe aus … bis zu 2 Minuten je nach Befehl.</div>}

      {res && (
        <>
          <div className="group-title">Ergebnisse · <code style={{ fontSize: 12 }}>$ {res.command}</code></div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
            {Object.entries(res.results).sort((a, b) => nameOf(a[0]).localeCompare(nameOf(b[0]))).map(([hk, r]) => (
              <div key={hk} className="panel" style={{ margin: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <b style={{ color: r.ok ? 'var(--ok,#4ade80)' : 'var(--bad,#f87171)' }}>{r.ok ? '✓' : '✕'}</b>
                  <b>{nameOf(hk)}</b>
                  <span className="muted" style={{ fontSize: 11 }}>{hk}</span>
                  <span style={{ flex: 1 }} />
                  {typeof r.ms === 'number' && <span className="muted" style={{ fontSize: 11 }}>{r.ms} ms</span>}
                </div>
                <pre style={{ fontSize: 11, background: 'var(--bg2,#111)', padding: 8, borderRadius: 6, overflowX: 'auto', maxHeight: 300, margin: 0, whiteSpace: 'pre-wrap' }}>{r.out || '(keine Ausgabe)'}</pre>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="muted" style={{ fontSize: 12, marginTop: 16 }}>
        Der Befehl läuft parallel auf allen gewählten Hosts (max. 40) via Proxmox <code>pct exec</code> als root und wird protokolliert.
        Für wiederkehrende Läufe (z.B. wöchentliches <code>apt update</code>) die Seite <b>Aufgaben</b> nutzen.
        Einfache Anführungszeichen (<code>'</code>) werden derzeit nicht unterstützt.
      </p>
    </>
  )
}
