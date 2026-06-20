import { useEffect, useRef, useState } from 'react'
import { getJSON, postJSON } from '../api.js'

export default function Inventory() {
  const [rows, setRows] = useState([])
  const [q, setQ] = useState('')
  const [results, setResults] = useState(null)
  const [openHost, setOpenHost] = useState(null)
  const [pkgs, setPkgs] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const deb = useRef(null)

  async function load() { setRows(await getJSON('/api/inventory').catch(() => [])) }
  useEffect(() => { load() }, [])

  function flash(t) { setMsg(t); setTimeout(() => setMsg(''), 2500) }

  useEffect(() => {
    clearTimeout(deb.current)
    if (!q.trim()) { setResults(null); return }
    deb.current = setTimeout(async () => {
      setResults(await getJSON(`/api/inventory/search?q=${encodeURIComponent(q.trim())}`).catch(() => []))
    }, 350)
    return () => clearTimeout(deb.current)
  }, [q])

  async function scan(key) {
    setBusy(key)
    try { const r = await postJSON(`/api/inventory/${encodeURIComponent(key)}/scan`)
      flash(r.ok ? `${key}: ${r.pkg_count} Pakete erfasst` : `Fehler: ${r.error}`); load() }
    catch (e) { flash(`Fehler: ${e.message}`) }
    finally { setBusy('') }
  }
  async function scanAll() {
    setBusy('all')
    try { const r = await postJSON('/api/inventory/scan-all'); flash(r.msg || 'gestartet')
      setTimeout(load, 8000); setTimeout(load, 20000) }
    finally { setBusy('') }
  }
  async function openPackages(key) {
    if (openHost === key) { setOpenHost(null); setPkgs(null); return }
    setOpenHost(key); setPkgs(null)
    const d = await getJSON(`/api/inventory/${encodeURIComponent(key)}`).catch(() => null)
    setPkgs(d?.packages || {})
  }

  return (
    <>
      {msg && <div className="toast">{msg}</div>}

      <div className="actions" style={{ marginBottom: 18 }}>
        <input className="inp" style={{ flex: 1, minWidth: 240 }}
          placeholder="🔎 Paket suchen (z.B. openssl, log4j, curl) — über alle CTs"
          value={q} onChange={e => setQ(e.target.value)} />
        <button className="btn" disabled={busy === 'all'} onClick={scanAll}>
          {busy === 'all' ? 'scannt …' : '⟳ Alle scannen'}
        </button>
      </div>

      {results !== null && (
        <>
          <div className="group-title">Suchergebnisse · {results.length}</div>
          <div className="panel" style={{ marginBottom: 22 }}>
            {results.length === 0 && <div className="muted">nichts gefunden (sind die CTs schon gescannt?)</div>}
            {results.map((r, i) => (
              <div className="kv" key={i}>
                <span className="mono">{r.package}</span>
                <span className="mono" style={{ color: 'var(--accent)' }}>{r.version}</span>
                <span className="muted">{r.host_key} · {r.os}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="group-title">CT-Inventar · {rows.length}</div>
      <div className="panel">
        {rows.length === 0 && <div className="muted">Noch nichts gescannt — „Alle scannen" klicken.</div>}
        {rows.map(r => (
          <div key={r.host_key}>
            <div className="inv-row">
              <span className="he-key mono">{r.host_key}{r.vmid ? ` · CT${r.vmid}` : ''}</span>
              <span>{r.os || '—'}</span>
              <span className="mono">py {r.python || '—'}</span>
              <span className="mono muted">{r.kernel || ''}</span>
              <span className="mono">{r.pkg_count ?? 0} Pakete</span>
              <span className="muted" style={{ fontSize: 12 }}>{r.scanned_at ? new Date(r.scanned_at * 1000).toLocaleString() : ''}</span>
              <span className="actions">
                <button className="btn" disabled={busy === r.host_key} onClick={() => scan(r.host_key)}>{busy === r.host_key ? '…' : 'Scan'}</button>
                <button className="btn" onClick={() => openPackages(r.host_key)}>{openHost === r.host_key ? 'zu' : 'Pakete'}</button>
              </span>
            </div>
            {openHost === r.host_key && (
              <div className="logs" style={{ maxHeight: 280, margin: '4px 0 14px' }}>
                {pkgs == null && <div className="muted">lädt …</div>}
                {pkgs && Object.entries(pkgs).sort().map(([n, v]) => <div key={n}>{n} <span className="muted">{v}</span></div>)}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  )
}
