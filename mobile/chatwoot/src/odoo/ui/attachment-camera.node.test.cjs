/** Actual AttachmentTools with native-picker seams; not an authenticated device upload test. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const renderer = require('react-test-renderer');
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function fixture() {
  const events = [];
  const control = { permission: 'granted', result: { assets: [{ uri: 'file:///private/capture.jpg', fileName: 'capture.jpg', type: 'image/jpeg' }] } };
  const staged = { uri: 'file:///owned/stage.jpg', name: 'capture.jpg', kind: 'image' };
  const native = { View: 'View', Platform: { OS: 'android' }, PermissionsAndroid: {
    PERMISSIONS: { CAMERA: 'android.permission.CAMERA' }, RESULTS: { GRANTED: 'granted' },
    request: async permission => { events.push(['permission', permission]); return control.permission; },
  } };
  const modules = { react: React, 'react/jsx-runtime': require('react/jsx-runtime'), 'react-native': native,
    './components': { Button: 'Button', IconButton: 'IconButton', colors: {}, styles: { row: {} } },
    './dictionary': { errorWord: () => 'error' },
    '../runtime': { stageFile: async () => { throw new Error('must use captured intent'); } },
    'react-native-image-picker': {
      launchCamera: async options => { events.push(['camera', options]); return control.result; },
      launchImageLibrary: async options => { events.push(['gallery', options]); return control.result; },
    },
    '@react-native-documents/picker': { types: { pdf: 'pdf', plainText: 'text', docx: 'docx', xlsx: 'xlsx' },
      pick: async () => { events.push(['file']); return [{ uri: 'content://private/document', name: 'document.pdf', type: 'application/pdf' }]; },
      isErrorWithCode: () => false, errorCodes: { OPERATION_CANCELED: 'cancelled' } },
  };
  const code = ts.transpileModule(readFileSync(join(__dirname, 'MediaTools.tsx'), 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports, require: name => modules[name] ?? {} });
  const props = { room: { id: 4 }, disabled: false, allowAttachments: true, language: 'ar', t: word => word,
    voice: { recording: false }, hasText: false, onSendText() {},
    report: word => events.push(['error', word]), enqueue: async () => { throw new Error('must use captured intent'); },
    beginAttachment: () => { events.push(['begin']); return {
      stage: async input => { events.push(['stage', input]); return staged; },
      enqueue: async value => { assert.equal(value, staged); events.push(['enqueue']); },
      cancel: () => { events.push(['cancel']); },
    }; },
  };
  let mounted;
  return { control, events, props,
    async mount() { await renderer.act(async () => { mounted = renderer.create(React.createElement(module.exports.AttachmentTools, props)); }); },
    async choose(kind, doubleTap = true) {
      await renderer.act(async () => mounted.root.findAllByType('IconButton').find(n => n.props.icon === 'attach').props.onPress());
      const button = mounted.root.findAllByType('Button').find(n => n.props.title === kind);
      assert.ok(button, `${kind} action exists`);
      await renderer.act(async () => { button.props.onPress(); if (doubleTap) button.props.onPress(); });
    },
    async close() { await renderer.act(async () => mounted?.unmount()); },
  };
}

test('camera captures intent before native permission, stages privately and enqueues once without saving to photos', async () => {
  const app = fixture();
  try {
    await app.mount(); await app.choose('camera');
    assert.deepEqual(app.events.map(e => e[0]), ['begin', 'permission', 'camera', 'stage', 'enqueue', 'cancel']);
    assert.equal(app.events[1][1], 'android.permission.CAMERA');
    assert.equal(app.events[2][1].saveToPhotos, false);
    assert.equal(app.events[3][1].kind, 'image');
  } finally { await app.close(); }
});

test('denied camera permission and cancelled capture never stage or enqueue an attachment', async () => {
  for (const scenario of ['denied', 'cancelled', 'unavailable']) {
    const app = fixture();
    if (scenario === 'denied') app.control.permission = 'denied';
    if (scenario === 'cancelled') app.control.result = { didCancel: true };
    if (scenario === 'unavailable') app.control.result = { errorCode: 'camera_unavailable' };
    try {
      await app.mount(); await app.choose('camera');
      assert.equal(app.events.some(e => ['stage', 'enqueue'].includes(e[0])), false);
      assert.equal(app.events.at(-1)[0], 'cancel');
      const errors = app.events.filter(e => e[0] === 'error').map(e => e[1]);
      assert.deepEqual(errors, scenario === 'denied' ? ['noCamera'] : scenario === 'unavailable' ? ['cameraUnavailable'] : []);
    } finally { await app.close(); }
  }
});

test('gallery and document selection use the same captured intent without requesting camera access', async () => {
  for (const kind of ['photo', 'file']) {
    const app = fixture();
    try {
      await app.mount(); await app.choose(kind);
      assert.deepEqual(app.events.map(e => e[0]), ['begin', kind === 'photo' ? 'gallery' : 'file', 'stage', 'enqueue', 'cancel']);
    } finally { await app.close(); }
  }
});

test('unauthorized attachment start never opens a native picker or camera permission prompt', async () => {
  const app = fixture();
  app.props.beginAttachment = () => { throw new Error('stale authority'); };
  try {
    await app.mount(); await app.choose('camera', false);
    assert.deepEqual(app.events, [['error', 'error']]);
  } finally { await app.close(); }
});
