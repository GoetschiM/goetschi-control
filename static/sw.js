// RRM – Service Worker (installierbare App)
// Seiten und API kommen immer frisch aus dem Netz. Zwischengespeichert werden nur
// Dateien, die sich nie aendern: gehashte Build-Dateien und Icons.
const CACHE = 'rrm-static-v1';
const PRECACHE = [
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const OFFLINE = `<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Offline</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0e14;color:#e6ebf2;
font:15px/1.5 system-ui,sans-serif;padding:24px}main{max-width:340px}h1{font-size:20px;margin:0 0 6px}
p{color:#8a97ab;margin:0 0 18px}button{background:#4f8cff;color:#fff;border:0;border-radius:8px;
padding:10px 14px;font:inherit;font-weight:600;cursor:pointer}</style>
<main><h1>Keine Verbindung</h1><p>Das Dashboard ist gerade nicht erreichbar. Prüfe das Netzwerk oder die VPN-Verbindung.</p>
<button onclick="location.reload()">Erneut versuchen</button></main></html>`;

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Seiten: Netz zuerst, ohne Netz ein schlichter Offline-Hinweis
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
    return;
  }
  // Unveraenderliche Dateien: aus dem Zwischenspeicher, sonst laden und ablegen
  if (url.pathname.startsWith('/static/spa/assets/') || url.pathname.startsWith('/static/icons/')) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }))
    );
  }
  // Alles andere (API, Login, Socket) geht unveraendert ans Netz.
});
