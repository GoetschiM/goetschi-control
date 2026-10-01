import { useEffect, useState } from 'react'
import { getJSON, postJSON } from '../api.js'

// Bestätigungsdialog in der Seite (statt confirm()), optional mit Eingabe des Namens.
export function useConfirm() {
  const [req, setReq] = useState(null)
  const ask = (opts) => new Promise(res => setReq({ ...opts, res }))
  const el = req && (
    <div className="palette-scrim" onMouseDown={() => { req.res(false); setReq(null) }}>
      <div className="palette confirm" onMouseDown={e => e.stopPropagation()}>
        <div className="confirm-title">{req.title}</div>
        <div className="muted">{req.text}</div>
        {req.typeName && <ConfirmInput name={req.typeName} onOk={() => { req.res(true); setReq(null) }} />}
        {!req.typeName && (
          <div className="actions" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
            <button className="btn ghost" onClick={() => { req.res(false); setReq(null) }}>Abbrechen</button>
            <button className={`btn ${req.danger ? 'danger' : ''}`} onClick={() => { req.res(true); setReq(null) }}>{req.ok || 'OK'}</button>
          </div>
        )}
      </div>
    </div>
  )
  return [ask, el]
}

function ConfirmInput({ name, onOk }) {
  const [v, setV] = useState('')
  return (
    <div style={{ marginTop: 14 }}>
      <div className="muted small" style={{ marginBottom: 6 }}>Zum Bestätigen <b className="mono">{name}</b> eintippen:</div>
      <div className="actions">
        <input id="confirm-name" className="inp" style={{ flex: 1 }} value={v} onChange={e => setV(e.target.value)} autoFocus />
        <button className="btn danger" disabled={v !== name} onClick={onOk}>Endgültig löschen</button>
      </div>
    </div>
  )
}

// Panel: Agent (Version, Update, Deinstallation) und Proxmox (Autostart, Backup)
export function HostAdmin({ host, agentOnline, onFlash }) {
  const [ask, confirmEl] = useConfirm()
  const [busy, setBusy] = useState('')
  const [pve, setPve] = useState(null)
  const [storages, setStorages] = useState([])
  const [storage, setStorage] = useState('')
  const key = encodeURIComponent(host.key)

  useEffect(() => {
    if (!host.ct_id) return
    getJSON(`/api/pve/${host.ct_id}/info`).then(setPve).catch(() => {})
    getJSON('/api/pve/storages').then(s => { setStorages(s); setStorage(s[0]?.storage || '') }).catch(() => {})
  }, [host.ct_id])

  async function run(id, fn) {
    setBusy(id)
    try { const r = await fn(); onFlash(r?.ok === false ? `Fehler: ${r.error}` : (r?.msg || 'erledigt')) }
    catch (e) { onFlash('Fehler: ' + e.message) }
    finally { setBusy('') }
  }

  return (
    <div className="panel">
      {confirmEl}
      <h3>Verwaltung</h3>
      <div className="admin-row">
        <div>
          <b>Agent</b>
          <div className="muted small">{agentOnline ? `läuft${host.agent?.version ? ` · v${host.agent.version}` : ''}` : 'nicht installiert oder nicht erreichbar'}</div>
        </div>
        {agentOnline ? (
          <div className="actions">
            <button className="btn" disabled={!!busy} onClick={() => run('upd', () => postJSON(`/api/agent-admin/${key}/update`))}>
              {busy === 'upd' ? '…' : 'Aktualisieren'}</button>
            <button className="btn ghost" disabled={!!busy} onClick={async () => {
              if (await ask({ title: 'Agent deinstallieren?', text: `Der Agent wird auf ${host.name} gestoppt und entfernt. Der Host bleibt in der Übersicht, aber ohne Details.`, ok: 'Deinstallieren', danger: true }))
                run('uni', () => postJSON(`/api/agent-admin/${key}/uninstall`, { confirm: true }))
            }}>Deinstallieren</button>
          </div>
        ) : <a className="btn" href="/connect">Installieren</a>}
      </div>

      {host.ct_id && (
        <>
          <div className="admin-row">
            <div>
              <b>Autostart</b>
              <div className="muted small">Container startet mit dem Proxmox-Host</div>
            </div>
            <button className={`switch ${pve?.onboot ? 'on' : ''}`} disabled={!pve || !!busy} aria-pressed={!!pve?.onboot}
              onClick={() => run('boot', async () => {
                const r = await postJSON(`/api/pve/${host.ct_id}/onboot`, { on: !pve.onboot })
                if (r.ok) setPve(p => ({ ...p, onboot: !p.onboot }))
                return r.ok ? { msg: `Autostart ${!pve.onboot ? 'an' : 'aus'}` } : r
              })}><span /></button>
          </div>
          <div className="admin-row">
            <div>
              <b>Backup</b>
              <div className="muted small">
                {pve?.backups?.length ? `letztes: ${new Date(pve.backups[0].start * 1000).toLocaleString()} · ${pve.backups[0].status || 'läuft'}` : 'noch keins über Proxmox'}
              </div>
            </div>
            <div className="actions">
              <select className="inp" id="backup-storage" value={storage} onChange={e => setStorage(e.target.value)}>
                {storages.map(s => <option key={s.storage} value={s.storage}>{s.storage} ({s.avail_gb} GB frei)</option>)}
              </select>
              <button className="btn" disabled={!!busy || !storage} onClick={() => run('bk', () => postJSON(`/api/pve/${host.ct_id}/backup`, { storage }))}>
                {busy === 'bk' ? '…' : 'Jetzt sichern'}</button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// Aktionen pro Docker-Container
export function DockerActions({ hostKey, name, up, policy, onDone, onFlash }) {
  const [ask, confirmEl] = useConfirm()
  const [busy, setBusy] = useState(false)
  const auto = policy && policy !== 'no'
  async function act(action, confirm = false) {
    setBusy(true)
    try {
      const r = await postJSON(`/api/docker/${encodeURIComponent(hostKey)}/action`, { name, action, confirm })
      onFlash(r.ok ? `${name}: ${r.msg}` : `Fehler: ${r.error}`); onDone?.()
    } catch (e) { onFlash('Fehler: ' + e.message) }
    finally { setBusy(false) }
  }
  return (
    <span className="row-actions">
      {confirmEl}
      {up
        ? <button className="icon-btn" title="Stoppen" disabled={busy} onClick={() => act('stop')}>⏹</button>
        : <button className="icon-btn" title="Starten" disabled={busy} onClick={() => act('start')}>▶</button>}
      <button className="icon-btn" title="Neu starten" disabled={busy} onClick={() => act('restart')}>↻</button>
      {policy !== undefined && (
        <button className={`tag ${auto ? 'ok' : ''}`} title="Autostart (Docker-Restart-Policy)" disabled={busy}
          onClick={() => act(auto ? 'autostart_off' : 'autostart_on')}>{auto ? 'Autostart' : 'kein Autostart'}</button>
      )}
      <button className="icon-btn danger" title="Löschen" disabled={busy} onClick={async () => {
        if (await ask({ title: `Container ${name} löschen?`, text: 'Der Container wird gestoppt und entfernt. Volumes bleiben erhalten, das Image auch.', typeName: name }))
          act('remove', true)
      }}>🗑</button>
    </span>
  )
}
