const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');

const pwa = path.join(__dirname, '..', 'static', 'pwa');
const css = fs.readFileSync(path.join(pwa, 'css', 'components.css'), 'utf8');
const screens = fs.readFileSync(path.join(pwa, 'js', 'screens.js'), 'utf8');

function rule(selector) {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const match = css.match(new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, 'm'));
    assert.ok(match, `Missing ${selector} rule`);
    return match[1];
}

test('drawer width remains fixed as projects load', () => {
    const drawer = rule('.drawer');
    const content = rule('.drawer-content');
    assert.match(drawer, /(?:^|;)\s*width\s*:\s*70vw\s*(?:;|$)/);
    assert.doesNotMatch(drawer, /max-content/);
    assert.doesNotMatch(content, /max-content/);
    assert.match(content, /(?:^|;)\s*width\s*:\s*100%\s*(?:;|$)/);
    assert.match(rule(':root'), /--drawer-w\s*:\s*70vw/);
    assert.doesNotMatch(screens, /setProperty\s*\(\s*['"]--drawer-w['"]/);
});
