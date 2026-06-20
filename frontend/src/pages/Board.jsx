import { useEffect, useRef, useState } from 'react'
import { getJSON, putJSON } from '../api.js'

export default function Board() {
  const [tiles, setTiles] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [edit, setEdit] = useState(false)
  const [form, setForm] = useState({ name: '', url: '', icon: '🔗' })
  const [msg, setMsg] = useState('')
  const drag = useRef(null)

  useEffect(() => { getJSON('/api/board').then(t => { setTiles(Array.isArray(t) ? t : []); setLoaded(true) }).catch(() => setLoaded(true)) }, [])

  function flash(t) { setMsg(t); setTimeout(() => setMsg(''), 2000) }
  async function save(next) {
    setTiles(next)
    try { await putJSON('/api/board', next); flash('gespeichert') } catch (e) { flash('Fehler: ' + e.message) }
  }

  function addTile() {
    if (!form.url.trim()) return
    const t = { name: form.name.trim() || form.url, url: form.url.trim(), icon: form.icon.trim() || '🔗', cat: 'custom' }
    save([...tiles, t]); setForm({ name: '', url: '', icon: '🔗' })
  }
  function remove(i) { save(tiles.filter((_, idx) => idx !== i)) }
  async function fillDiscovered() {
    const disc = await getJSON('/api/board/discovered').catch(() => [])
    const urls = new Set(tiles.map(t => t.url))
    const merged = [...tiles, ...disc.filter(d => !urls.has(d.url))]
    save(merged); flash(`${merged.length - tiles.length} neue Dienste übernommen`)
  }

  // drag & drop reorder
  function onDrop(i) {
    const from = drag.current
    if (from == null || from === i) return
    const next = [...tiles]
    const [m] = next.splice(from, 1)
    next.splice(i, 0, m)
    drag.current = null
    save(next)
  }

  if (!loaded) return <div className="center-msg">lädt …</div>

  return (
    <>
      {msg && <div className="toast">{msg}</div>}
      <div className="actions" style={{ marginBottom: 16 }}>
        <button className={`btn ${edit ? 'primary' : ''}`} onClick={() => setEdit(e => !e)}>{edit ? '✓ Fertig' : '✎ Bearbeiten'}</button>
        <button className="btn" onClick={fillDiscovered}>⟲ Aus Diensten füllen</button>
      </div>

      {edit && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="actions">
            <input className="inp" style={{ width: 54 }} value={form.icon} onChange={e => setForm({ ...form, icon: e.target.value })} placeholder="🔗" />
            <input className="inp" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Name" />
            <input className="inp" style={{ flex: 1, minWidth: 200 }} value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="https://…" />
            <button className="btn primary" onClick={addTile}>+ Hinzufügen</button>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Kacheln per Drag&Drop anordnen. ✕ zum Entfernen.</p>
        </div>
      )}

      <div className="board">
        {tiles.length === 0 && <div className="muted">Noch keine Kacheln — „Aus Diensten füllen" oder „Bearbeiten".</div>}
        {tiles.map((t, i) => (
          <a key={i} className="tile" href={edit ? undefined : t.url} target="_blank" rel="noreferrer"
            draggable={edit}
            onDragStart={() => (drag.current = i)}
            onDragOver={e => edit && e.preventDefault()}
            onDrop={() => onDrop(i)}
            onClick={e => { if (edit) e.preventDefault() }}>
            {edit && <button className="tile-x" onClick={e => { e.preventDefault(); remove(i) }}>✕</button>}
            <span className="tile-ico">{t.icon || '🔗'}</span>
            <span className="tile-name">{t.name}</span>
            <span className="tile-url">{(t.url || '').replace(/^https?:\/\//, '').slice(0, 28)}</span>
          </a>
        ))}
      </div>
    </>
  )
}
