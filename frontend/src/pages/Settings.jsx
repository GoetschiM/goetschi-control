import { useEffect, useState } from 'react'
import { getJSON, postJSON, patchJSON, delJSON } from '../api.js'

const CATEGORIES = ['infra', 'core', 'agent', 'ai', 'voice', 'trading', 'app', 'sonstige']

export default function Settings() {
  const [live, setLive] = useState(null)
  const [meta, setMeta] = useState({})
  const [settings, setSettings] = useState(null)
  const [tokens, setTokens] = useState([])
  const [audit, setAudit] = useState([])
  const [newToken, setNewToken] = useState('')
  const [users, setUsers] = useState([])
  const [me, setMe] = useState(null)
  const [nu, setNu] = useState({ username: '', password: '', role: 'viewer' })
  const [mfaSetup, setMfaSetup] = useState(null)
  const [mfaCode, setMfaCode] = useState('')
  const [pw, setPw] = useState({ old: '', new: '' })
  const [thr, setThr] = useState(null)
  const [msg, setMsg] = useState('')

  async function changePw() {
    if (!pw.old || !pw.new) return flash('Beide Felder nötig')
    try { await postJSON('/api/me/password', pw); setPw({ old: '', new: '' }); flash('Passwort geändert') }
    catch (e) { flash('Fehler: ' + e.message) }
  }

  async function startMfa() { try { setMfaSetup(await postJSON('/api/mfa/setup')) } catch (e) { flash('Fehler: ' + e.message) } }
  async function confirmMfa() {
    try { await postJSON('/api/mfa/enable', { code: mfaCode }); setMfaSetup(null); setMfaCode(''); flash('2FA aktiviert'); loadAll() }
    catch (e) { flash('Fehler: ' + e.message) }
  }
  async function disableMfa() {
    const code = prompt('Aktuellen 2FA-Code eingeben:'); if (!code) return
    try { await postJSON('/api/mfa/disable', { code }); flash('2FA deaktiviert'); loadAll() } catch (e) { flash('Fehler: ' + e.message) }
  }

  async function loadAll() {
    const [l, m, s, t, a, u, meR, th] = await Promise.all([
      getJSON('/api/live').catch(() => null),
      getJSON('/api/host_meta').catch(() => ({})),
      getJSON('/api/settings').catch(() => null),
      getJSON('/api/tokens').catch(() => []),
      getJSON('/api/audit').catch(() => []),
      getJSON('/api/users').catch(() => []),
      getJSON('/api/me').catch(() => null),
      getJSON('/api/alert-thresholds').catch(() => null),
    ])
    setLive(l); setMeta(m || {}); setSettings(s); setTokens(t || []); setAudit(a || [])
    setUsers(Array.isArray(u) ? u : []); setMe(meR); setThr(th)
  }

  async function saveThresholds() {
    try {
      const r = await postJSON('/api/alert-thresholds', thr)
      setThr(r.thresholds); flash('Schwellwerte gespeichert')
    } catch (e) { flash('Fehler: ' + e.message) }
  }

  async function createUser() {
    if (!nu.username.trim() || !nu.password) return flash('Benutzername + Passwort nötig')
    try { await postJSON('/api/users', nu); setNu({ username: '', password: '', role: 'viewer' }); flash('Benutzer angelegt'); loadAll() }
    catch (e) { flash('Fehler: ' + e.message) }
  }
  async function deleteUser(u) {
    if (!confirm(`Benutzer "${u}" löschen?`)) return
    try { await delJSON(`/api/users/${encodeURIComponent(u)}`); flash('gelöscht'); loadAll() }
    catch (e) { flash('Fehler: ' + e.message) }
  }
  useEffect(() => { loadAll() }, [])

  function flash(t) { setMsg(t); setTimeout(() => setMsg(''), 2500) }

  async function saveHost(key, patch) {
    try { await patchJSON(`/api/host_meta/${encodeURIComponent(key)}`, patch); flash(`Gespeichert: ${key}`) }
    catch (e) { flash(`Fehler: ${e.message}`) }
  }

  async function createToken() {
    if (!newToken.trim()) return
    try { await postJSON('/api/tokens', { name: newToken.trim() }); setNewToken(''); flash('Token erstellt'); loadAll() }
    catch (e) { flash(`Fehler: ${e.message}`) }
  }
  async function deleteToken(id) {
    if (!confirm('Token löschen?')) return
    try { await delJSON(`/api/tokens/${id}`); flash('Token gelöscht'); loadAll() }
    catch (e) { flash(`Fehler: ${e.message}`) }
  }
  async function testTelegram() {
    try { const r = await postJSON('/api/telegram/test'); flash(r?.ok === false ? `Telegram: ${r.error}` : 'Telegram-Test gesendet') }
    catch (e) { flash(`Fehler: ${e.message}`) }
  }

  const hosts = live?.hosts || []

  return (
    <>
      {msg && <div className="toast">{msg}</div>}

      <div className="group-title">Zwei-Faktor (2FA){me ? ` — ${me.username}` : ''}</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        {me?.mfa ? (
          <div className="actions"><span className="role-admin">✓ 2FA aktiv</span><button className="btn danger" onClick={disableMfa}>Deaktivieren</button></div>
        ) : mfaSetup ? (
          <div>
            <p className="muted">Scanne den QR-Code mit deiner Authenticator-App (z.B. Google Authenticator, Aegis), dann gib den 6-stelligen Code ein:</p>
            <div className="mfa-qr" dangerouslySetInnerHTML={{ __html: mfaSetup.qr_svg }} />
            <p className="muted mono" style={{ fontSize: 11 }}>Secret (manuell): {mfaSetup.secret}</p>
            <div className="actions">
              <input className="inp" placeholder="6-stelliger Code" value={mfaCode} onChange={e => setMfaCode(e.target.value)} inputMode="numeric" maxLength={6} />
              <button className="btn primary" onClick={confirmMfa}>Aktivieren</button>
            </div>
          </div>
        ) : (
          <div className="actions"><span className="muted">2FA ist nicht aktiv</span><button className="btn primary" onClick={startMfa}>2FA aktivieren</button></div>
        )}
      </div>

      <div className="group-title">Passwort ändern</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        <div className="actions">
          <input className="inp" type="password" placeholder="Aktuelles Passwort" value={pw.old} onChange={e => setPw({ ...pw, old: e.target.value })} />
          <input className="inp" type="password" placeholder="Neues Passwort" value={pw.new} onChange={e => setPw({ ...pw, new: e.target.value })} />
          <button className="btn primary" onClick={changePw}>Ändern</button>
        </div>
      </div>

      {me?.role === 'admin' && (
        <>
          <div className="group-title">Benutzer & Rollen</div>
          <div className="panel" style={{ marginBottom: 22 }}>
            <div className="actions" style={{ marginBottom: 12 }}>
              <input className="inp" placeholder="Benutzername" value={nu.username} onChange={e => setNu({ ...nu, username: e.target.value })} />
              <input className="inp" type="password" placeholder="Passwort" value={nu.password} onChange={e => setNu({ ...nu, password: e.target.value })} />
              <select className="inp" value={nu.role} onChange={e => setNu({ ...nu, role: e.target.value })}>
                <option value="viewer">viewer (nur lesen)</option>
                <option value="admin">admin (voll)</option>
              </select>
              <button className="btn primary" onClick={createUser}>+ Anlegen</button>
            </div>
            {users.map(u => (
              <div className="kv" key={u.username}>
                <span><b>{u.username}</b> {u.username === me.username && <span className="muted">(du)</span>}</span>
                <span className={u.role === 'admin' ? 'role-admin' : 'role-viewer'}>{u.role}</span>
                <span className="muted" style={{ flex: 1, textAlign: 'right', fontSize: 12 }}>{u.last_login ? `zuletzt ${u.last_login}` : 'nie'}</span>
                {u.username !== me.username && <button className="btn danger" onClick={() => deleteUser(u.username)}>Löschen</button>}
              </div>
            ))}
            <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>Viewer können alles sehen, aber keine Aktionen ausführen (Reboot, Container, Terminal, Automationen …).</p>
          </div>
        </>
      )}

      <div className="group-title">Hosts bearbeiten</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        {hosts.length === 0 && <div className="muted">lädt …</div>}
        {hosts.map(h => <HostRow key={h.key} h={h} meta={meta[h.key] || {}} onSave={saveHost} />)}
      </div>

      <div className="group-title">API-Tokens</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        <div className="actions" style={{ marginBottom: 12 }}>
          <input className="inp" placeholder="Token-Name (z.B. host-xyz)" value={newToken}
            onChange={e => setNewToken(e.target.value)} />
          <button className="btn" onClick={createToken}>+ Erstellen</button>
        </div>
        {tokens.length === 0 && <div className="muted">keine Tokens</div>}
        {tokens.map(t => (
          <div className="kv" key={t.id}>
            <span>{t.name}</span>
            <span className="mono" style={{ flex: 1, textAlign: 'center', color: 'var(--text-mute)' }}>
              {(t.token || '').slice(0, 8)}…
            </span>
            <button className="btn danger" onClick={() => deleteToken(t.id)}>Löschen</button>
          </div>
        ))}
      </div>

      <div className="group-title">Alarm-Schwellwerte</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        {!thr ? <div className="muted">lädt …</div> : (
          <>
            <div className="actions" style={{ flexWrap: 'wrap' }}>
              <ThrInput label="CPU warn %" v={thr.cpu_warn} on={v => setThr({ ...thr, cpu_warn: v })} />
              <ThrInput label="RAM warn %" v={thr.ram_warn} on={v => setThr({ ...thr, ram_warn: v })} />
              <ThrInput label="Disk crit %" v={thr.disk_crit} on={v => setThr({ ...thr, disk_crit: v })} />
              <ThrInput label="SSL warn Tage" v={thr.ssl_warn_days} on={v => setThr({ ...thr, ssl_warn_days: v })} />
              {me?.role === 'admin' && <button className="btn primary" onClick={saveThresholds}>Speichern</button>}
            </div>
            <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
              Gilt für Dashboard-Alarme und Telegram-Benachrichtigungen (Auswertung alle ~5s).
            </p>
          </>
        )}
      </div>

      <div className="group-title">Konfiguration</div>
      <div className="panel" style={{ marginBottom: 22 }}>
        <div className="kv"><span>Agent-Token</span><span className="mono">{mask(settings?.agent_token)}</span></div>
        <div className="kv"><span>Agent-Port</span><span className="mono">{settings?.agent_port ?? '—'}</span></div>
        <div className="kv"><span>Dashboard-URL</span><span className="mono">{settings?.dashboard_url ?? '—'}</span></div>
        <div className="kv">
          <span>Status-Seite (öffentlich)</span>
          <span>
            <span className={`pill ${settings?.public_status ? 'online' : 'offline'}`}>
              {settings?.public_status ? 'aktiv' : 'aus'}
            </span>
            {settings?.public_status && <a className="btn" style={{ marginLeft: 10 }} href="/status" target="_blank" rel="noreferrer">Öffnen</a>}
          </span>
        </div>
        <div className="kv"><span>Version</span><span className="mono">{settings?.version ?? '—'}</span></div>
        <div className="kv">
          <span>Telegram</span>
          <span>
            <span className={`pill ${settings?.telegram_configured ? 'online' : 'offline'}`}>
              {settings?.telegram_configured ? 'konfiguriert' : 'nicht konfiguriert'}
            </span>
            <button className="btn" style={{ marginLeft: 10 }} onClick={testTelegram}>Test senden</button>
          </span>
        </div>
      </div>

      <div className="group-title">Audit-Log (letzte Aktionen)</div>
      <div className="panel">
        <div className="logs" style={{ maxHeight: 280 }}>
          {audit.length === 0 && <div className="muted">leer</div>}
          {audit.slice(0, 60).map((a, i) => (
            <div key={i}>{new Date(a.ts * 1000).toLocaleString()} · {a.user} · {a.action} · {a.host} · {a.detail}</div>
          ))}
        </div>
      </div>
    </>
  )
}

function HostRow({ h, meta, onSave }) {
  const [name, setName] = useState(meta.display_name || h.name || '')
  const [cat, setCat] = useState(meta.category || h.category || 'sonstige')
  const [notes, setNotes] = useState(meta.notes || '')
  return (
    <div className="host-edit">
      <span className="he-key mono">{h.ip}{h.ct_id ? ` · CT${h.ct_id}` : ''}</span>
      <input className="inp" value={name} onChange={e => setName(e.target.value)} placeholder="Anzeigename" />
      <select className="inp" value={cat} onChange={e => setCat(e.target.value)}>
        {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
      </select>
      <input className="inp" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Notizen" />
      <button className="btn" onClick={() => onSave(h.key, { display_name: name, category: cat, notes })}>Speichern</button>
    </div>
  )
}

function ThrInput({ label, v, on }) {
  return (
    <label className="muted" style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
      {label}
      <input className="inp" type="number" min="1" max="365" value={v ?? ''}
        onChange={e => on(e.target.value === '' ? '' : Number(e.target.value))} style={{ width: 110 }} />
    </label>
  )
}

function mask(v) { return v ? v.slice(0, 6) + '…' + v.slice(-3) : '—' }
