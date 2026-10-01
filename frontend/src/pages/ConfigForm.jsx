import { useEffect, useState } from 'react'
import { getJSON, postJSON } from '../api.js'

// Integrationen direkt in der Oberflaeche einrichten. Geheimnisse werden nie angezeigt;
// ein leeres Geheimnis-Feld laesst den gespeicherten Wert unveraendert.
export default function ConfigForm({ onFlash }) {
  const [cfg, setCfg] = useState(null)
  const [vals, setVals] = useState({})
  const [open, setOpen] = useState(null)
  const [busy, setBusy] = useState(false)
  const [restarting, setRestarting] = useState(false)

  async function load() {
    const c = await getJSON('/api/config').catch(() => null)
    setCfg(c)
    const v = {}
    c?.groups.forEach(g => g.fields.forEach(f => { v[f.key] = f.secret ? '' : f.value }))
    setVals(v)
  }
  useEffect(() => { load() }, [])

  async function save(group) {
    setBusy(true)
    try {
      const values = {}
      group.fields.forEach(f => { values[f.key] = vals[f.key] ?? '' })
      const r = await postJSON('/api/config', { values })
      onFlash(r.changed?.length ? `${group.name}: gespeichert` : 'Keine Änderung')
      await load()
    } catch (e) { onFlash('Fehler: ' + e.message) }
    finally { setBusy(false) }
  }
  async function clear(key) {
    await postJSON('/api/config/clear', { key }).catch(() => {}); load()
  }
  async function restart() {
    setRestarting(true)
    await postJSON('/api/app/restart').catch(() => {})
    const t0 = Date.now()
    const wait = async () => {
      try { await getJSON('/api/me'); window.location.reload() }
      catch { if (Date.now() - t0 < 60000) setTimeout(wait, 2000); else setRestarting(false) }
    }
    setTimeout(wait, 3000)
  }

  if (!cfg) return <div className="panel muted">lädt …</div>
  return (
    <>
      {cfg.restart_pending && (
        <div className="setup" style={{ marginBottom: 14 }}>
          <div className="setup-head" style={{ marginBottom: 0 }}>
            <div>
              <div className="setup-title">Änderungen gespeichert</div>
              <div className="muted">Sie werden nach einem Neustart des Dashboards aktiv (dauert wenige Sekunden).</div>
            </div>
            <button className="btn" disabled={restarting} onClick={restart}>{restarting ? 'startet neu …' : 'Jetzt neu starten'}</button>
          </div>
        </div>
      )}
      <div className="cfg-groups">
        {cfg.groups.map(g => {
          const done = g.fields.filter(f => f.set).length
          const isOpen = open === g.name
          return (
            <div className={`cfg-group ${isOpen ? 'open' : ''}`} key={g.name}>
              <button className="cfg-head" onClick={() => setOpen(isOpen ? null : g.name)}>
                <span className={`dot-s ${done ? 's-online' : 's-off'}`} />
                <b>{g.name}</b>
                <span className="muted">{done ? `${done} von ${g.fields.length} gesetzt` : 'nicht eingerichtet'}</span>
                <span className="cfg-chev">{isOpen ? '−' : '+'}</span>
              </button>
              {isOpen && (
                <div className="cfg-body">
                  {g.fields.map(f => (
                    <label className="cfg-field" key={f.key} htmlFor={`cfg-${f.key}`}>
                      <span>{f.label} <span className="mono muted small">{f.key}</span></span>
                      <span className="cfg-input">
                        <input id={`cfg-${f.key}`} className="inp" type={f.secret ? 'password' : 'text'} autoComplete="off"
                          placeholder={f.secret ? (f.set ? '•••••••• gesetzt – leer lassen zum Behalten' : f.hint) : f.hint}
                          value={vals[f.key] ?? ''} onChange={e => setVals(v => ({ ...v, [f.key]: e.target.value }))} />
                        {f.secret && f.set && f.source === 'ui' && <button type="button" className="btn ghost" onClick={() => clear(f.key)}>Löschen</button>}
                      </span>
                    </label>
                  ))}
                  <div className="actions" style={{ marginTop: 6 }}>
                    <button className="btn" disabled={busy} onClick={() => save(g)}>Speichern</button>
                    {g.name === 'Telegram-Alarme' && (
                      <button className="btn ghost" onClick={async () => {
                        const r = await postJSON('/api/telegram/test').catch(e => ({ ok: false, error: e.message }))
                        onFlash(r?.ok === false ? `Telegram: ${r.error || 'fehlgeschlagen'}` : 'Testnachricht gesendet')
                      }}>Test senden</button>
                    )}
                  </div>
                  {g.name === 'Telegram-Alarme' && (
                    <div className="muted small" style={{ marginTop: 8 }}>
                      Bot bei @BotFather anlegen, Token hier eintragen. Dem Bot eine Nachricht schreiben, dann zeigt
                      https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates deine Chat-ID.
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}
