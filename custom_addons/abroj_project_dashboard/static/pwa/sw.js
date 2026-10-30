'use strict';
const CACHE = 'abroj-v5';
const SHELL = '/abroj_project_dashboard/static/pwa/index.html';
const ASSETS = [SHELL, '/abroj_project_dashboard/static/pwa/app.js', '/abroj_project_dashboard/static/pwa/i18n.js', '/abroj_project_dashboard/static/pwa/app.css'];
self.addEventListener('install', event => event.waitUntil(
  caches.open(CACHE).then(cache => cache.addAll(ASSETS.map(url => new Request(url, {credentials: 'omit'})))).then(() => self.skipWaiting())
));
self.addEventListener('activate', event => event.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('abroj-v') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())
));
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  // Never intercept /web/, /odoo/, /report/, JSON/RPC or non-GET requests.
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if ([request.headers.get('accept'), request.headers.get('content-type')].some(value => value?.toLowerCase().includes('json'))) return;
  if (request.mode === 'navigate') {
    if (url.pathname !== '/abroj/app') return;
    event.respondWith(fetch(request).catch(() => caches.open(CACHE).then(cache => cache.match(SHELL))));
    return;
  }
  if (url.search || !ASSETS.includes(url.pathname)) return;
  event.respondWith(caches.open(CACHE).then(cache => cache.match(url.pathname)).then(response => response || fetch(request)));
});
