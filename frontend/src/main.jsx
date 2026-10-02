import React from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App.jsx'
import './styles.css'

// Service Worker fuer die installierbare App. Alte Worker (frueher unter /static/sw.js,
// lieferten veraltete Dateien aus) und ihre Caches werden entfernt; der neue Worker
// (/sw.js) laedt Seiten und API immer frisch und speichert nur gehashte Dateien und Icons.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations()
    .then(rs => rs.forEach(r => {
      const url = r.active?.scriptURL || r.installing?.scriptURL || r.waiting?.scriptURL || ''
      if (!url.endsWith('/sw.js') || url.includes('/static/')) r.unregister()
    }))
    .catch(() => {})
  if (window.caches) caches.keys().then(ks => ks.filter(k => !k.startsWith('rrm-static-')).forEach(k => caches.delete(k))).catch(() => {})
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {})
  })
}

// Installations-Angebot des Browsers merken, damit die App einen eigenen Knopf zeigen kann.
window.__rrmInstall = null
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault()
  window.__rrmInstall = e
  window.dispatchEvent(new Event('rrm-installable'))
})
window.addEventListener('appinstalled', () => {
  window.__rrmInstall = null
  window.dispatchEvent(new Event('rrm-installable'))
})

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
)
