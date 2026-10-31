'use strict';
const VERSION = 'ASSET_VERSION_PLACEHOLDER';
const CACHE = 'abroj-v36-' + VERSION;
const SHELL = '/abroj/app';
const ASSETS = ['/abroj_project_dashboard/static/pwa/js/media.js', '/abroj_project_dashboard/static/pwa/js/app.js', '/abroj_project_dashboard/static/pwa/js/screens.js', '/abroj_project_dashboard/static/pwa/js/i18n.js', '/abroj_project_dashboard/static/pwa/css/tokens.css', '/abroj_project_dashboard/static/pwa/css/base.css', '/abroj_project_dashboard/static/pwa/css/components.css', '/abroj_project_dashboard/static/pwa/css/screens.css', '/abroj_project_dashboard/static/pwa/logo-navy.png', '/abroj_project_dashboard/static/pwa/logo-white.png', '/abroj_project_dashboard/static/pwa/icon-192.png', '/abroj_project_dashboard/static/pwa/icon-512.png', '/abroj_project_dashboard/static/pwa/icon-maskable-512.png', '/abroj_project_dashboard/static/pwa/apple-touch-icon.png'];
self.addEventListener('install', event => event.waitUntil(
  caches.open(CACHE).then(async cache => {
    await cache.addAll(ASSETS.map(url => new Request(url + '?v=' + VERSION, {credentials: 'omit', cache: 'reload'})));
    try {
      const shell = new Request(SHELL, {credentials: 'same-origin', cache: 'reload'});
      const response = await fetch(shell);
      if (response.ok && !response.redirected) await cache.put(shell, response);
    } catch (_) {}
  }).then(() => self.skipWaiting())
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
  if (!ASSETS.includes(url.pathname) || url.searchParams.get('v') !== VERSION) return;
  event.respondWith(caches.open(CACHE).then(cache => cache.match(request)).then(response => response || fetch(request)));
});
