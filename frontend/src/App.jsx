import { useState } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import Overview from './pages/Overview.jsx'
import HostDetail from './pages/HostDetail.jsx'

const NAV = [
  { to: '/', ico: '▦', label: 'Übersicht', end: true },
  { to: '/topology', ico: '⤳', label: 'Topologie' },
  { to: '/alerts', ico: '◬', label: 'Alarme' },
]

function Placeholder({ title }) {
  return <div className="center-msg">{title} — kommt in einem der nächsten Schritte.</div>
}

export default function App() {
  const [navOpen, setNavOpen] = useState(false)
  const loc = useLocation()

  return (
    <div className={`app ${navOpen ? 'nav-open' : ''}`}>
      <aside className="sidebar">
        <div className="brand"><span className="dot" /> Goetschi Control</div>
        <nav className="nav" onClick={() => setNavOpen(false)}>
          {NAV.map(n => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => (isActive ? 'active' : '')}>
              <span className="ico">{n.ico}</span>{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="foot">v0.1 · RRM redesign</div>
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
            <Route path="/topology" element={<Placeholder title="Topologie" />} />
            <Route path="/alerts" element={<Placeholder title="Alarme" />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

function titleFor(path) {
  if (path.startsWith('/host/')) return 'Service'
  if (path.startsWith('/topology')) return 'Topologie'
  if (path.startsWith('/alerts')) return 'Alarme'
  return 'Übersicht'
}
