// AirLink PWA Service Worker (v2.0.0)
// Strategy: network-first for everything, cache fallback for offline static.
const CACHE_NAME = 'airlink-v2.0.0';
const APP_SHELL = [
  '/',
  '/css/style.css',
  '/js/app.js',
  '/manifest.json',
  '/icons/icon-192.png'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = event.request.url;
  // API, media, aur auth requests hamesha network ko jaane do
  if (url.includes('/api/') || url.includes('/download/') || url.includes('/auth/') ||
      url.includes('/history') || url.includes('/sync/') || url.includes('/heartbeat') ||
      url.includes('/users/') || url.includes('/send/') || url.includes('/react') ||
      url.includes('/pin') || url.includes('/qr') || url.includes('/info')) {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
