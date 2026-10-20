const assert = require('node:assert/strict');
const { readFileSync, existsSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');
const root = join(__dirname, '../../..');

function component() {
  const mod = { exports: {} };
  const code = ts.transpileModule(readFileSync(join(__dirname, 'Brand.tsx'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { module: mod, exports: mod.exports, require(name) {
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }) };
    if (name === 'react-native') return { Image: 'Image', View: 'View' };
    if (name.endsWith('.png')) { assert.ok(existsSync(join(__dirname, name))); return name; }
    return {};
  } });
  return mod.exports.Brand;
}

test('approved artwork is fixed-size, accessible, contained and never mirrored', () => {
  const Brand = component();
  for (const variant of ['header', 'login', 'drawer', 'mark']) {
    const tree = Brand({ variant });
    assert.equal(tree.props.style.direction, 'ltr');
    assert.equal(tree.props.style.backgroundColor, '#ffffff');
    assert.ok(tree.props.style.width > 0 && tree.props.style.height > 0);
    assert.equal(tree.props.children.props.resizeMode, 'contain');
    assert.equal(tree.props.children.props.accessibilityLabel, 'BWork');
    assert.equal(tree.props.children.props.style.transform, undefined);
  }
});

test('header and narrow-drawer brand slots account for raster clear space without widening the drawer', () => {
  const Brand = component();
  const header = Brand({ variant: 'header' }).props.style;
  const drawer = Brand({ variant: 'drawer' }).props.style;
  assert.equal(header.width, 128);
  assert.equal(header.height, 38.4);
  assert.equal(drawer.width, 140);
  assert.equal(drawer.height, 42);
  for (const size of [header, drawer]) {
    assert.ok(Math.abs(size.width / size.height - 10 / 3) < 0.001);
    const image = Brand({ variant: size === header ? 'header' : 'drawer' }).props.children.props.style;
    // Approved b and work share a baseline; frame the full 1294x325 ink bounds.
    const scale = image.width / 2169;
    assert.ok(325 * scale >= 30);
    assert.ok(image.left + 465 * scale >= 0);
    assert.ok(image.left + 1759 * scale <= size.width);
    assert.ok(image.top + 198 * scale >= 0);
    assert.ok(image.top + 523 * scale <= size.height);
  }
  assert.ok(drawer.width <= 320 * 0.65 - 16 - 44 - 8,
    'fits beside the unchanged toggle/gap inside the existing 65% drawer');
  const source = readFileSync(join(__dirname, 'NavigationDrawer.tsx'), 'utf8');
  assert.ok(source.includes('<Brand variant="drawer" />'));
});

test('single blue b wordmark uses the exact approved preview in every wordmark surface', () => {
  const crypto = require('node:crypto');
  const bytes = readFileSync(join(root, 'assets/bwork/bwork-wordmark-approved-20261019.png'));
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),
    'bf06eaa8fbde40b57c040c4292aa81226e1930dc350837d591888a3bc197fc1d');
  assert.equal(bytes.readUInt32BE(16), 2169);
  assert.equal(bytes.readUInt32BE(20), 725);
  assert.ok(bytes.length < 1500000);
  const Brand = component();
  for (const variant of ['header', 'login', 'drawer']) {
    const tree = Brand({ variant });
    assert.match(tree.props.children.props.source, /bwork-wordmark-approved-20261019\.png$/);
    assert.equal(tree.props.style.overflow, 'hidden');
    const image = tree.props.children.props.style;
    assert.ok(Math.abs(image.width / image.height - 2169 / 725) < 0.0001);
  }
  assert.match(Brand({ variant: 'mark' }).props.children.props.source, /bwork-icon-1024\.png$/);
});

test('native branding preserves update identity and uses separate Odoo assets', () => {
  const config = readFileSync(join(root, 'app.config.ts'), 'utf8');
  assert.ok(config.includes("name: trial ? 'BWork' : 'Chatwoot'"));
  // Branding protects update identity, not a stale release number. Actual upgrade ordering
  // remains part of APK acceptance; legitimate version increments must not fail this test.
  assert.match(config, /version:\s*trial\s*\?\s*'\d+\.\d+\.\d+'/);
  assert.match(config, /versionCode:\s*[1-9]\d*\b/);
  assert.ok(config.includes('package: trial ? target.applicationId'));
  assert.equal(require('../../../bwork-profile.cjs').profile({}).applicationId,require('../../../compatibility/identities.json').qa.applicationId);
  assert.ok(config.includes('scheme: trial ? target.schemes'));
  assert.ok(config.includes("trial ? './assets/bwork/bwork-adaptive-1024.png' : './assets/adaptive-icon.png'"));
});

test('bundled source raster is preserved, PNG dimensions bounded, tokens meet button contrast', () => {
  const crypto = require('node:crypto');
  const assets = join(root, 'assets/bwork');
  const original = readFileSync(join(assets, 'bwork-original.png'));
  assert.equal(crypto.createHash('sha256').update(original).digest('hex'),
    'b85f025bf140e1269b3d070029c9758c630c567d03eabe53667693af7f05dd8a');
  for (const name of ['bwork-icon-1024.png', 'bwork-adaptive-1024.png']) {
    const png = readFileSync(join(assets, name));
    assert.equal(png.readUInt32BE(16), 1024);
    assert.equal(png.readUInt32BE(20), 1024);
    assert.ok(png.length < 750000);
  }
  const rgb = [0x12,0x56,0xda].map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  const contrast = 1.05 / (.2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2] + .05);
  assert.ok(contrast >= 4.5);
});
