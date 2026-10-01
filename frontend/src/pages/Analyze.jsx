import { useEffect, useRef, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { getJSON, postJSON } from '../api.js'

const QUICK = [
  'Was ist gerade kritisch in der Infrastruktur?',
  'Welche Hosts haben auffällig hohe CPU- oder RAM-Last und warum?',
  'Fasse die aktiven Alarme zusammen und priorisiere sie.',
  'Wo wird der Speicherplatz knapp?',
]

// Chat mit dem KI-Assistenten. Antigravity antwortet zuerst mit einem Plan (nur lesen);
// "Ausführen" gibt den Plan frei. Gespräche bleiben gespeichert.
export default function Analyze() {
  const [params] = useSearchParams()
  const [hosts, setHosts] = useState([])
  const [hostKey, setHostKey] = useState(params.get('host') || '')
  const [q, setQ] = useState('')
  const [msgs, setMsgs] = useState([])
  const [conv, setConv] = useState(null)
  const [busy, setBusy] = useState('')
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [me, setMe] = useState(null)
  const end = useRef(null)
  const started = useRef(false)

  useEffect(() => {
    getJSON('/api/live').then(d => setHosts(d?.hosts || [])).catch(() => {})
    getJSON('/api/ai/status').then(setStatus).catch(() => setStatus({ ready: false }))
    getJSON('/api/me').then(setMe).catch(() => {})
    loadHistory()
  }, [])
  useEffect(() => {
    if (started.current) return
    started.current = true
    if (params.get('q')) send(params.get('q'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs, busy])

  function loadHistory() { getJSON('/api/ai/conversations').then(setHistory).catch(() => {}) }

  async function send(text = q, execute = false) {
    if ((!text.trim() && !execute) || busy) return
    const shown = execute ? 'Plan freigegeben – ausführen' : text.trim()
    setMsgs(m => [...m, { role: 'user', text: shown, mode: execute ? 'execute' : 'plan' }])
    setQ(''); setBusy(execute ? 'execute' : 'plan')
    try {
      const r = await postJSON('/api/ai/analyze', {
        question: execute ? '' : text.trim(), host_key: hostKey || null, conversation: conv, execute,
      })
      if (r.conversation_id) setConv(r.conversation_id)
      setMsgs(m => [...m, r.ok
        ? { role: 'assistant', text: r.answer, mode: r.mode || 'plan', model: r.model }
        : { role: 'error', text: r.error || 'Fehler' }])
      loadHistory()
    } catch (e) {
      setMsgs(m => [...m, { role: 'error', text: e.message }])
    } finally { setBusy('') }
  }

  async function openConv(id) {
    const rows = await getJSON(`/api/ai/conversations?id=${encodeURIComponent(id)}`).catch(() => [])
    setConv(id); setMsgs(rows.map(r => ({ role: r.role, text: r.text, mode: r.mode })))
  }
  function newConv() { setConv(null); setMsgs([]) }

  const isAdmin = me?.role !== 'viewer'
  const lastIdx = msgs.length - 1
  const lastIsPlan = msgs[lastIdx]?.role === 'assistant' && msgs[lastIdx]?.mode === 'plan'

  if (status && !status.ready) {
    return (
      <div className="panel">
        <b>Die KI ist noch nicht eingerichtet.</b>
        <div className="muted" style={{ marginTop: 6 }}>
          {status.provider === 'agy'
            ? 'Antigravity (agy) wurde auf diesem Server nicht gefunden.'
            : 'Für LiteLLM fehlen Adresse oder API-Key.'}{' '}
          <Link to="/settings#integrationen" style={{ color: 'var(--accent)' }}>Einstellungen › KI</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-layout">
      <aside className="chat-side">
        <button className="btn" onClick={newConv}>+ Neues Gespräch</button>
        <div className="group-title" style={{ margin: '16px 0 8px' }}>Verlauf</div>
        {history.length === 0 && <div className="muted small">noch keine Gespräche</div>}
        {history.map(h => (
          <button key={h.id} className={`chat-hist ${conv === h.id ? 'on' : ''}`} onClick={() => openConv(h.id)}>
            <span>{h.title || 'Gespräch'}</span>
            <span className="muted small">{new Date(h.last * 1000).toLocaleString()}</span>
          </button>
        ))}
      </aside>

      <section className="chat-main">
        <div className="chat-head">
          <select className="inp" id="ai-host" value={hostKey} onChange={e => setHostKey(e.target.value)} disabled={!!conv}>
            <option value="">Ganze Infrastruktur</option>
            {hosts.map(h => <option key={h.key} value={h.key}>{h.name}</option>)}
          </select>
          <span className="muted small">
            {status?.provider === 'agy' ? 'Antigravity · antwortet zuerst mit einem Plan, ausgeführt wird erst nach Freigabe' : 'LiteLLM · nur Analyse'}
          </span>
        </div>

        <div className="chat-log">
          {msgs.length === 0 && (
            <div className="chat-empty">
              <div className="muted" style={{ marginBottom: 10 }}>Frag nach Zustand, Ursachen oder lass dir eine Änderung vorschlagen.</div>
              <div className="ai-quick">
                {QUICK.map(p => <button key={p} className="chip" onClick={() => send(p)}>{p}</button>)}
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              {m.role === 'assistant' && <div className="msg-meta">{m.mode === 'execute' ? 'Ausgeführt' : 'Plan / Antwort'}</div>}
              <div className="msg-text">{m.text}</div>
              {i === lastIdx && lastIsPlan && isAdmin && status?.provider === 'agy' && (
                <div className="msg-actions">
                  <button className="btn danger" disabled={!!busy} onClick={() => send('', true)}>Plan ausführen</button>
                  <span className="muted small">Antigravity setzt die Schritte dann selbst um. Wird protokolliert.</span>
                </div>
              )}
            </div>
          ))}
          {busy && <div className="msg assistant pending">{busy === 'execute' ? 'Antigravity führt aus …' : 'Antigravity denkt nach …'}</div>}
          <div ref={end} />
        </div>

        <form className="chat-input" onSubmit={e => { e.preventDefault(); send() }}>
          <textarea id="ai-q" className="inp" rows={2} value={q} placeholder={conv ? 'Rückfrage oder Änderungswunsch …' : 'Frag die Infrastruktur … (Strg+Enter sendet)'}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send() } }} />
          <button className="btn primary" type="submit" disabled={!!busy || !q.trim()}>Senden</button>
        </form>
      </section>
    </div>
  )
}
