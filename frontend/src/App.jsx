import { useState, useEffect } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { getJSON } from './api.js'
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
import Board from './pages/Board.jsx'
import Automate from './pages/Automate.jsx'
import Tasks from './pages/Tasks.jsx'
import Ansible from './pages/Ansible.jsx'
import Audit from './pages/Audit.jsx'
import Events from './pages/Events.jsx'
import Metrics from './pages/Metrics.jsx'
import Integrations from './pages/Integrations.jsx'
import Grafana from './pages/Grafana.jsx'

const NAV = [
  { to: '/', ico: '▦', label: 'Übersicht', end: true },
  { to: '/board', ico: '◰', label: 'Dienste' },
  { to: '/topology', ico: '⤳', label: 'Topologie' },
  { to: '/metrics', ico: '◍', label: 'Metriken' },
  { to: '/grafana', ico: '▨', label: 'Grafana' },
  { to: '/inventory', ico: '▤', label: 'Inventar' },
  { to: '/analyze', ico: '✦', label: 'KI-Analyse' },
  { to: '/automate', ico: '⚡', label: 'Automationen' },
  { to: '/tasks', ico: '◴', label: 'Aufgaben' },
  { to: '/ansible', ico: '⌘', label: 'Befehle' },
  { to: '/events', ico: '◔', label: 'Aktivität' },
  { to: '/audit', ico: '☰', label: 'Protokoll' },
  { to: '/maintenance', ico: '◷', label: 'Wartung' },
  { to: '/integrations', ico: '⧉', label: 'Integrationen' },
  { to: '/alerts', ico: '◬', label: 'Alarme' },
  { to: '/settings', ico: '⚙', label: 'Einstellungen' },
]

const IDLE_MS = 5 * 60 * 1000  // auto-logout after 5 min inactivity

export default function App() {
  const [navOpen, setNavOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('gc_collapsed') === '1')
  const [me, setMe] = useState(null)
  const loc = useLocation()

  useEffect(() => { getJSON('/api/me').then(setMe).catch(() => {}) }, [])

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
        <div className="foot">v0.4 · RRM</div>
      </aside>
      <div className="scrim" onClick={() => setNavOpen(false)} />

      <div className="main">
        <header className="topbar">
          <button className="menu-btn" onClick={() => setNavOpen(o => !o)}>☰</button>
          <h1>{titleFor(loc.pathname)}</h1>
          <div className="spacer" />
          {me && <span className="user-badge">{me.username} · <b className={me.role === 'admin' ? 'role-admin' : 'role-viewer'}>{me.role}</b></span>}
          <a className="btn" href="/logout">Logout</a>
        </header>
        <div className="content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/board" element={<Board />} />
            <Route path="/host/:key" element={<HostDetail />} />
            <Route path="/host/:key/c/:name" element={<ContainerDetail />} />
            <Route path="/host/:key/terminal" element={<Terminal />} />
            <Route path="/topology" element={<Topology />} />
            <Route path="/metrics" element={<Metrics />} />
            <Route path="/grafana" element={<Grafana />} />
            <Route path="/inventory" element={<Inventory />} />
            <Route path="/analyze" element={<Analyze />} />
            <Route path="/automate" element={<Automate />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/ansible" element={<Ansible />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/events" element={<Events />} />
            <Route path="/maintenance" element={<Maintenance />} />
            <Route path="/integrations" element={<Integrations />} />
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
  if (path.startsWith('/board')) return 'Dienste'
  if (path.includes('/c/')) return 'Container'
  if (path.startsWith('/host/')) return 'Service'
  if (path.startsWith('/topology')) return 'Topologie'
  if (path.startsWith('/metrics')) return 'Metriken'
  if (path.startsWith('/grafana')) return 'Grafana'
  if (path.startsWith('/inventory')) return 'Inventar'
  if (path.startsWith('/analyze')) return 'KI-Analyse'
  if (path.startsWith('/automate')) return 'Automationen'
  if (path.startsWith('/tasks')) return 'Aufgaben'
  if (path.startsWith('/ansible')) return 'Befehle'
  if (path.startsWith('/audit')) return 'Protokoll'
  if (path.startsWith('/events')) return 'Aktivität'
  if (path.startsWith('/maintenance')) return 'Wartung'
  if (path.startsWith('/integrations')) return 'Integrationen'
  if (path.startsWith('/alerts')) return 'Alarme'
  if (path.startsWith('/settings')) return 'Einstellungen'
  return 'Übersicht'
}
