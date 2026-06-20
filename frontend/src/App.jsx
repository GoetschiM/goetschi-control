import { useState, useEffect } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import Overview from './pages/Overview.jsx'
import HostDetail from './pages/HostDetail.jsx'
import ContainerDetail from './pages/ContainerDetail.jsx'
import Topology from './pages/Topology.jsx'
import Alerts from './pages/Alerts.jsx'
import Settings from './pages/Settings.jsx'
import Terminal from './pages/Terminal.jsx'
import Inventory from './pages/Inventory.jsx'
import Analyze from './pages/Analyze.jsx'
import Maintenance from './pages/Maintenance.jsx'

const NAV = [
  { to: '/', ico: '▦', label: 'Übersicht', end: true },
  { to: '/topology', ico: '⤳', label: 'Topologie' },
  { to: '/inventory', ico: '▤', label: 'Inventar' },
  { to: '/analyze', ico: '✦', label: 'KI-Analyse' },
  { to: '/maintenance', ico: '◷', label: 'Wartung' },
  { to: '/alerts', ico: '◬', label: 'Alarme' },
  { to: '/settings', ico: '⚙', label: 'Einstellungen' },
]

const IDLE_MS = 5 * 60 * 1000  // auto-logout after 5 min inactivity

export default function App() {
  const [navOpen, setNavOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('gc_collapsed') === '1')
  const loc = useLocation()

  function toggleCollapsed() {
    setCollapsed(c => { localStorage.setItem('gc_collapsed', c ? '0' : '1'); return !c })
  }

  // auto-logout on inactivity
  useEffect(() => {
    let t
    const reset = () => { clearTimeout(t); t = setTimeout(() => { window.location.href = '/logout' }, IDLE_MS) }
    const evs = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart']
    evs.forEach(e => window.addEventListener(e, reset, { passive: true }))
    reset()
    return () => { clearTimeout(t); evs.forEach(e => window.removeEventListener(e, reset)) }
  }, [])

  return (
    <div className={`app ${navOpen ? 'nav-open' : ''} ${collapsed ? 'collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="dot" /> <span className="brand-label">Goetschi Control</span>
          <button className="collapse-btn" onClick={toggleCollapsed} title="Menü ein-/ausklappen">‹</button>
        </div>
        <nav className="nav" onClick={() => setNavOpen(false)}>
          {NAV.map(n => (
            <NavLink key={n.to} to={n.to} end={n.end} title={n.label}
              className={({ isActive }) => (isActive ? 'active' : '')}>
              <span className="ico">{n.ico}</span><span className="nav-label">{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="foot">v0.3 · RRM</div>
      </aside>
      <div className="scrim" onClick={() => setNavOpen(false)} />

      <div className="main">
        <header className="topbar">
          <button className="menu-btn" onClick={() => setNavOpen(o => !o)}>☰</button>
          <h1>{titleFor(loc.pathname)}</h1>
          <div className="spacer" />
          <a className="btn" href="/logout">Logout</a>
        </header>
        <div className="content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/host/:key" element={<HostDetail />} />
            <Route path="/host/:key/c/:name" element={<ContainerDetail />} />
            <Route path="/host/:key/terminal" element={<Terminal />} />
            <Route path="/topology" element={<Topology />} />
            <Route path="/inventory" element={<Inventory />} />
            <Route path="/analyze" element={<Analyze />} />
            <Route path="/maintenance" element={<Maintenance />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

function titleFor(path) {
  if (path.endsWith('/terminal')) return 'Terminal'
  if (path.includes('/c/')) return 'Container'
  if (path.startsWith('/host/')) return 'Service'
  if (path.startsWith('/topology')) return 'Topologie'
  if (path.startsWith('/inventory')) return 'Inventar'
  if (path.startsWith('/analyze')) return 'KI-Analyse'
  if (path.startsWith('/maintenance')) return 'Wartung'
  if (path.startsWith('/alerts')) return 'Alarme'
  if (path.startsWith('/settings')) return 'Einstellungen'
  return 'Übersicht'
}
