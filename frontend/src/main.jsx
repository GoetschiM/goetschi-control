import React from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App.jsx'
import './styles.css'

// One-time cleanup: the legacy frontend registered an aggressive PWA service
// worker that kept serving stale assets ("old layout"). Unregister any existing
// worker and drop its caches so the redesign always loads fresh.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations()
    .then(rs => rs.forEach(r => r.unregister()))
    .catch(() => {})
  if (window.caches) caches.keys().then(ks => ks.forEach(k => caches.delete(k))).catch(() => {})
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
)
