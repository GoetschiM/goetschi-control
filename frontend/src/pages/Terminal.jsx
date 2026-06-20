import { useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { io } from 'socket.io-client'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

export default function Terminal() {
  const { key } = useParams()
  const hostKey = decodeURIComponent(key)
  const elRef = useRef(null)
  const wrapRef = useRef(null)

  useEffect(() => {
    const term = new XTerm({
      fontFamily: 'var(--mono), monospace',
      fontSize: 13,
      cursorBlink: true,
      theme: { background: '#0b0e14', foreground: '#e6ebf2', cursor: '#4f8cff' },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(elRef.current)
    try { fit.fit() } catch {}

    const socket = io({ path: '/socket.io', transports: ['websocket', 'polling'] })

    socket.on('connect', () => {
      socket.emit('ssh_open', { host: hostKey, cols: term.cols, rows: term.rows })
    })
    socket.on('ssh_data', (m) => term.write(m.d ?? ''))
    socket.on('disconnect', () => term.write('\r\n\x1b[33m[GL] Socket getrennt\x1b[0m\r\n'))

    term.onData((d) => socket.emit('ssh_input', { d }))

    const onResize = () => {
      try {
        fit.fit()
        socket.emit('ssh_resize', { cols: term.cols, rows: term.rows })
      } catch {}
    }
    window.addEventListener('resize', onResize)
    const ro = new ResizeObserver(onResize)
    if (wrapRef.current) ro.observe(wrapRef.current)

    return () => {
      window.removeEventListener('resize', onResize)
      ro.disconnect()
      socket.close()
      term.dispose()
    }
  }, [hostKey])

  return (
    <>
      <div className="crumbs">
        <Link to="/">Übersicht</Link> / <Link to={`/host/${encodeURIComponent(hostKey)}`}>{hostKey}</Link> / Terminal
      </div>
      <div className="term-wrap" ref={wrapRef}>
        <div className="term-host" ref={elRef} />
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
        SSH via Proxmox <code>pct enter</code> (für LXC) bzw. direktes SSH. Sitzung schließt beim Verlassen der Seite.
      </p>
    </>
  )
}
