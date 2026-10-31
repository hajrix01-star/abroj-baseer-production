const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('project gallery pages use the files and photos name', () => {
  const xml = fs.readFileSync(path.join(__dirname, '..', 'views', 'dashboard.xml'), 'utf8');
  assert.doesNotMatch(xml, /string="المعرض"/);
  assert.equal((xml.match(/<page string="الملفات والصور">/g) || []).length, 2);
});
