import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getJSON } from './api.js'

// Schnellsuche (Strg+K): Hosts nach Name/IP/CT und alle Seiten.
export default function Palette({ onClose, nav }) {
  const [q, setQ] = useState('')
  const [hosts, setHosts] = useState([])
  const [sel, setSel] = useState(0)
  const go = useNavigate()
  const inp = useRef(null)

  useEffect(() => {
    inp.current?.focus()
    getJSON('/api/live').then(d => setHosts(d.hosts || [])).catch(() => {})
  }, [])

  const items = useMemo(() => {
    const t = q.trim().toLowerCase()
    const pages = nav.map(n => ({ kind: 'Seite', label: n.label, sub: '', to: n.to }))
    const hs = hosts.map(h => ({
      kind: 'Host', label: h.name, sub: [h.ip, h.ct_id ? `CT ${h.ct_id}` : ''].filter(Boolean).join(' · '),
      to: `/host/${encodeURIComponent(h.key)}`, status: h.status,
    }))
    const all = [...hs, ...pages]
    if (!t) return all.slice(0, 12)
    return all.filter(i => `${i.label} ${i.sub}`.toLowerCase().includes(t)).slice(0, 20)
  }, [q, hosts, nav])

  useEffect(() => { setSel(0) }, [q])

  function pick(i) { if (!i) return; go(i.to); onClose() }
  function onKey(e) {
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, items.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(s - 1, 0)) }
    else if (e.key === 'Enter') pick(items[sel])
  }

  return (
    <div className="palette-scrim" onMouseDown={onClose}>
      <div className="palette" onMouseDown={e => e.stopPropagation()}>
        <input ref={inp} id="palette-q" className="palette-input" placeholder="Host, IP, CT-Nummer oder Seite …"
          value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey} />
        <div className="palette-list">
          {items.length === 0 && <div className="muted" style={{ padding: 14 }}>{hosts.length ? 'Nichts gefunden' : 'lädt …'}</div>}
          {items.map((i, idx) => (
            <button key={i.kind + i.to} className={`palette-item ${idx === sel ? 'sel' : ''}`}
              onMouseEnter={() => setSel(idx)} onClick={() => pick(i)}>
              {i.status ? <span className={`dot-s s-${i.status}`} /> : <span className="palette-kind">↗</span>}
              <span className="palette-label">{i.label}</span>
              <span className="muted mono palette-sub">{i.sub}</span>
              <span className="palette-kind">{i.kind}</span>
            </button>
          ))}
        </div>
        <div className="palette-foot muted">↑↓ auswählen · Enter öffnen · Esc schliessen</div>
      </div>
    </div>
  )
}
