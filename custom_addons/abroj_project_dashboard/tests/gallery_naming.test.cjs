const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('project gallery pages use the Library name', () => {
  const xml = fs.readFileSync(path.join(__dirname, '..', 'views', 'dashboard.xml'), 'utf8');
  assert.doesNotMatch(xml, /string="الملفات والصور"/);
  const i18n = fs.readFileSync(path.join(__dirname, "..", "static/pwa/js/i18n.js"), "utf8");
  assert.match(i18n, /"en": "Library"/);
  assert.match(i18n, /رفع من المعرض/);
  assert.equal((xml.match(/<page string="المكتبة">/g) || []).length, 2);
});
