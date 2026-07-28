/* Pelobrossss service worker — offline-first cache */
const CACHE = 'pelobrossss-v9';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon.svg',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './workouts.json'
];
// Workout history changes; the shell does not. Serving history cache-first
// would pin the app to whatever was cached the day it installed.
const FRESH = /workouts\.json$/;

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// workout data: network-first, refreshing the cached copy for offline use.
// everything else: cache-first, falling back to network, then to the cached
// index for navigations.
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  if (FRESH.test(new URL(e.request.url).pathname)) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).catch(() =>
      e.request.mode === 'navigate' ? caches.match('./index.html') : undefined
    ))
  );
});
