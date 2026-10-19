/** Render the actual component with native build metadata seams, without a device/Jest. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

function component(metadata) {
  const dictionary = { exports: {} };
  const dictionaryCode = ts.transpileModule(
    readFileSync(join(__dirname, 'dictionary.ts'), 'utf8'),
    {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    },
  ).outputText;
  vm.runInNewContext(dictionaryCode, { module: dictionary, exports: dictionary.exports });
  const source = readFileSync(join(__dirname, 'VersionLabel.tsx'), 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
  }).outputText;
  const modules = {
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }) },
    'react-native': { Text: 'Text' },
    'expo-application': metadata,
    './dictionary': dictionary.exports,
    './components': {
      styles: { muted: {} },
      direction: language => ({ writingDirection: language === 'ar' ? 'rtl' : 'ltr' }),
    },
  };
  const mod = { exports: {} };
  vm.runInNewContext(code, {
    module: mod,
    exports: mod.exports,
    require: name => modules[name] ?? {},
  });
  return mod.exports.VersionLabel;
}

test('header version reflects installed binary metadata in Arabic and English', () => {
  const render = component({ nativeApplicationVersion: '2.7.9', nativeBuildVersion: '42' });
  const ar = render({ language: 'ar' });
  const en = render({ language: 'en' });
  assert.equal(ar.props.children, 'الإصدار \u20662.7.9\u2069 · البناء \u206642\u2069');
  assert.equal(en.props.children, 'Version 2.7.9 · Build 42');
  assert.equal(ar.props.testID, 'odoo-app-version');
  assert.equal(ar.props.accessibilityLabel, 'الإصدار 2.7.9 · البناء 42');
});

test('upgrades and missing native metadata never display a hardcoded candidate version', () => {
  assert.equal(
    component({ nativeApplicationVersion: '3.0.1', nativeBuildVersion: '105' })({ language: 'en' })
      .props.children,
    'Version 3.0.1 · Build 105',
  );
  assert.equal(
    component({ nativeApplicationVersion: null, nativeBuildVersion: null })({ language: 'en' })
      .props.children,
    'Version — · Build —',
  );
});
