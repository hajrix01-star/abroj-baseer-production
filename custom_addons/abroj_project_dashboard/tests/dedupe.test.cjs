'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
test('project summary avoids repeated phase and financial lists while retaining their entries', () => {
  const app = read('static/pwa/js/app.js');
  const screens = read('static/pwa/js/screens.js');
  const legacy = app.slice(app.indexOf('async function legacyDetail'), app.indexOf('function edit('));
  assert.doesNotMatch(legacy, /p\.phases\.map|p\.contracts\.map|p\.vouchers\.map|cards\(\[p\]\)/);
  assert.match(screens, /\['phases',t\("s47"\)\]/);
  assert.match(screens, /documentList\(\['contract'\]\)/);
  assert.match(screens, /documentList\(\['payment','receipt','promissory'\]\)/);
  assert.match(screens, /cards\(\[p\]\)/);
});
test('shared empty state does not offer a redundant projects link by default', () => {
  const app = read('static/pwa/js/app.js');
  assert.match(app, /emptyState=\(message,action=null\)/);
  assert.match(app, /action\?`<button/);
  assert.match(read('static/pwa/js/screens.js'), /emptyState\(t\("s119"\), "fabSheet\(\)"\)/);
});
test('contracting form keeps financial totals once and gallery on both distinct forms', () => {
  const xml = read('views/dashboard.xml');
  assert.match(xml, /cash_balance.*total_received.*position="replace"/);
  assert.match(xml, /cash_balance.*total_paid.*position="replace"/);
  assert.equal((xml.match(/name="abroj_gallery_widget"/g) || []).length, 2);
  assert.match(xml, /inherit_id" ref="project\.edit_project"/);
  assert.match(xml, /inherit_id" ref="abroj_contracting\.project_form"/);
});

test('removed project feature is absent from client scripts', () => {
  const forbidden = ['project' + 'Lib' + 'rary', 'lib' + 'rary'];
  for (const file of ['static/pwa/js/screens.js', 'static/pwa/js/i18n.js']) {
    for (const term of forbidden) assert.ok(!read(file).includes(term));
  }
});
