const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const src = path.join(root, 'static/src');
const strings = new Set();
for (const file of fs.readdirSync(src).filter(f => /\.(js|xml)$/.test(f))) {
    const text = fs.readFileSync(path.join(src, file), 'utf8');
    for (const match of text.matchAll(/_t\(\s*(['"])((?:\\.|(?!\1).)*)\1\s*\)/g)) strings.add(match[2]);
}
for (const locale of ['ar.po', 'ar_001.po']) {
    const po = fs.readFileSync(path.join(root, 'i18n', locale), 'utf8');
    for (const str of strings) {
        const entry = `msgid ${JSON.stringify(str)}\nmsgstr `;
        const position = po.indexOf(entry);
        assert.ok(position >= 0 && !po.slice(position + entry.length).startsWith('""'), `${locale}: missing translation for ${str}`);
    }
}
const i18n = fs.readFileSync(path.join(root, 'static/pwa/js/i18n.js'), 'utf8');
const translations = vm.runInNewContext(i18n + '\ntranslations');
for (const [key, value] of Object.entries(translations)) if (value.en) assert.ok(value.ar, `PWA Arabic missing ${key}`);
