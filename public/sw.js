// Simple Service Worker for AirLink PWA
const CACHE_NAME = 'airlink-v1';
const ASSETS = [
  '/',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Let network handle API and file downloads, fallback to cache for static
  if (event.request.url.includes('/api/') || event.request.url.includes('/ws') || event.request.url.includes('/files/')) {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
