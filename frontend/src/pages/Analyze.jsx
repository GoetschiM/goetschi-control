import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getJSON, postJSON } from '../api.js'

const QUICK = [
  'Was ist gerade kritisch in der Infrastruktur?',
  'Welche Hosts haben auffällig hohe CPU- oder RAM-Last und warum?',
  'Fasse die aktiven Alarme zusammen und priorisiere sie.',
  'Gibt es Hinweise auf ein Problem in den Logs?',
]

export default function Analyze() {
  const [params] = useSearchParams()
  const [hosts, setHosts] = useState([])
  const [hostKey, setHostKey] = useState(params.get('host') || '')
  const [q, setQ] = useState(params.get('q') || '')
  const [answer, setAnswer] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    getJSON('/api/live').then(d => setHosts(d?.hosts || [])).catch(() => {})
  }, [])

  // auto-run if a question was passed via URL (e.g. from a host page)
  useEffect(() => {
    if (params.get('q')) ask(params.get('q'), params.get('host') || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function ask(question = q, host = hostKey) {
    if (!question.trim() || busy) return
    setBusy(true); setErr(''); setAnswer(null)
    try {
      const r = await postJSON('/api/ai/analyze', { question, host_key: host || null })
      if (r.ok) setAnswer(r.answer)
      else setErr(r.error || 'Fehler')
    } catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <>
      <div className="ai-bar">
        <select className="inp" value={hostKey} onChange={e => setHostKey(e.target.value)}>
          <option value="">Ganze Infrastruktur</option>
          {hosts.map(h => <option key={h.key} value={h.key}>{h.name}</option>)}
        </select>
      </div>

      <div className="ai-input">
        <textarea className="inp ai-q" rows={3} value={q}
          placeholder="Frag die Infrastruktur… z.B. „Warum ist CT110 langsam?“"
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) ask() }} />
        <button className="btn primary" disabled={busy || !q.trim()} onClick={() => ask()}>
          {busy ? 'analysiere …' : '🤖 Fragen'}
        </button>
      </div>

      <div className="ai-quick">
        {QUICK.map(p => (
          <button key={p} className="chip" disabled={busy} onClick={() => { setQ(p); ask(p) }}>{p}</button>
        ))}
      </div>

      {err && <div className="panel" style={{ color: 'var(--crit)', marginTop: 16 }}>Fehler: {err}</div>}
      {busy && <div className="center-msg">Die KI durchsucht Metriken, Logs und Alarme …</div>}
      {answer && (
        <div className="panel ai-answer" style={{ marginTop: 16 }}>
          <h3>Antwort · gemini-flash</h3>
          <div className="ai-text">{answer}</div>
        </div>
      )}
    </>
  )
}
