const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '..', 'static/pwa/js/app.js'), 'utf8');
const functions = app.slice(app.indexOf('async function refreshNotifications()'), app.indexOf("document.addEventListener('click',event=>{if(!event.target.closest('.notification-wrap'))"));
const nodes = {'notification-count': {}, 'notification-button': {setAttribute() {}}, 'notification-panel': {hidden: true}};
const calls = [];
const ctx = vm.createContext({document: {getElementById: id => nodes[id]}, lang: 'en', esc: s => String(s), t: s => s, toast() {}, rpc: async (url, params) => {calls.push([url, params]); return {count: 1, items: [{id: 5, body: 'Completed', date: '2026-01-01', category: 'done'}]};}});
vm.runInContext(functions, ctx);
(async () => {
  await ctx.toggleNotifications();
  assert.equal(nodes['notification-count'].textContent, '1');
  assert.match(nodes['notification-panel'].innerHTML, /Completed/);
  assert.match(nodes['notification-panel'].innerHTML, /notification-dot done/);
  await ctx.readNotification(5);
  assert.equal(calls[1][0], '/abroj/app/notifications/read');
  assert.equal(calls[1][1].message_id, 5);
})().catch(error => {console.error(error); process.exitCode = 1;});

// Execute all PWA scripts while the initial data request is still pending.
// This catches temporal-dead-zone errors and unguarded dashboard reads at startup.
{
  const element = () => ({hidden: true, style: {setProperty() {}, removeProperty() {}}, setAttribute() {}, addEventListener() {}, getBoundingClientRect: () => ({width: 240}), querySelector() {return null;}});
  const elements = new Map();
  const document = {documentElement: element(), body: element(), title: '', addEventListener() {}, querySelector(selector) {return Object.assign(element(), {content: selector.includes('user-lang') ? 'en' : '1'});}, getElementById(id) {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);}};
  const window = {addEventListener() {}, location: {reload() {}}, isSecureContext: false};
  const storage = {getItem() {return null;}, removeItem() {}};
  const context = vm.createContext({document, window, navigator: {onLine: false}, localStorage: storage, sessionStorage: storage, location: window.location, fetch: () => new Promise(() => {}), AbortController, setTimeout() {}, clearTimeout() {}, MutationObserver: class {observe() {}}, ResizeObserver: class {observe() {}}, console});
  for (const name of ['i18n.js', 'app.js', 'screens.js', 'media.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static/pwa/js', name), 'utf8'), context, {filename: name});
  }
  assert.match(elements.get('drawer').innerHTML, /Issue end-of-day report/);
  assert.doesNotThrow(() => context.toggleNotifications(false));
}
