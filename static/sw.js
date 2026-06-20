// Goetschi Labs Dashboard — Service Worker
// Ermöglicht Android App-Install (PWA) + Caching

const CACHE_NAME = 'gl-dashboard-v3';
const STATIC_ASSETS = [
  '/',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

// Install: Cache statische Assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: Räume alte Caches auf
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    })
  );
  self.clients.claim();
});

// Fetch: Netzwerk first, Cache fallback (für Live-Daten)
self.addEventListener('fetch', (event) => {
  // API-Calls nie cachen — immer live
  if (event.request.url.includes('/api/')) {
    return;
  }

  // Statische Assets: Cache-First
  if (STATIC_ASSETS.includes(new URL(event.request.url).pathname)) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request);
      })
    );
    return;
  }

  // Alles andere: Network-first
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Nur erfolgreiche Antworten cachen
        if (response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, clone);
          });
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});
