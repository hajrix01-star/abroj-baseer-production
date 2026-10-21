/** Render the actual timeline/composer with native seams; not an Android layout/device proof. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

function hooks() {
  const slots = [];
  let index = 0;
  let effects = [];
  return {
    react: {
      useRef(value) { const at = index++; return slots[at] ?? (slots[at] = { current: value }); },
      useState(value) {
        const at = index++;
        if (!(at in slots)) slots[at] = typeof value === 'function' ? value() : value;
        return [slots[at], next => { slots[at] = typeof next === 'function' ? next(slots[at]) : next; }];
      },
      useCallback(value, deps) {
        const at = index++;
        if (!slots[at] || deps.some((item, i) => item !== slots[at].deps[i])) slots[at] = { deps, value };
        return slots[at].value;
      },
      useMemo(factory, deps) {
        const at = index++;
        if (!slots[at] || deps.some((item, i) => item !== slots[at].deps[i])) slots[at] = { deps, value: factory() };
        return slots[at].value;
      },
      useEffect(callback, deps) {
        const at = index++;
        if (!slots[at] || deps.some((value, i) => value !== slots[at].deps[i])) {
          effects.push(() => { slots[at]?.cleanup?.(); slots[at] = { deps, cleanup: callback() }; });
        }
      },
    },
    render(fn) { index = 0; effects = []; const result = fn(); for (const effect of effects) effect(); return result; },
  };
}
const element = (type, props) => ({ type, props: props || {} });
const jsx = { jsx: element, jsxs: element, Fragment: 'Fragment' };
const colors = { white: 'white', border: 'border', chatBackground: 'history-surface', chatSent: 'sent-surface', composerBackground: 'composer-surface', danger: 'danger', blue: 'blue' };
const components = { Button: 'Button', Field: 'Field', Icon: 'Icon', IconButton: 'IconButton', Label: 'Label', Sheet: 'Sheet', colors,
  styles: { fill: { flex: 1 }, row: {}, card: {}, header: {}, text: {}, muted: {}, title: {} }, direction: language => ({ textAlign: language === 'ar' ? 'right' : 'left', writingDirection: language === 'ar' ? 'rtl' : 'ltr' }) };
function load(file, dependencies) {
  const compiled = ts.transpileModule(readFileSync(join(__dirname, file), 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => dependencies[name] ?? {}, console,
    Date: dependencies.Date ?? Date, setTimeout: dependencies.setTimeout ?? setTimeout, clearTimeout: dependencies.clearTimeout ?? clearTimeout,
    requestAnimationFrame: callback => { dependencies.frames?.push(callback); return dependencies.frames?.length ?? 1; },
    cancelAnimationFrame: id => { if (dependencies.frames) dependencies.frames[id - 1] = null; },
  }, { filename: file });
  return module.exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function one(tree, type, predicate = () => true) {
  const matches = nodes(tree).filter(node => node.type === type && predicate(node.props));
  assert.equal(matches.length, 1, `${type} unique match`);
  return matches[0].props;
}
async function settled() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
const attachment = { uri: 'file:///owned/stage.m4a', kind: 'audio', name: 'synthetic.m4a', mime: 'audio/mp4', size: 10, sha256: 'a'.repeat(64), upload_uuid: 'synthetic' };
const room = { id: 4, company_id: 1, membership_id: 9, name: 'Synthetic room', is_group: true };
const t = word => word;

function composer() {
  const state = hooks();
  const events = [];
  let release;
  const props = { room, disabled: false, hasText: false, allowAttachments: true, language: 'ar', t,
    children: element('Field', {}), report: word => events.push(['error', word]),
    enqueue: async value => { events.push(['attachment', value]); }, onSendText: () => events.push(['text']),
    voice: { recording: false, seconds: 65, start: async () => { events.push(['start']); }, finish: async () => { events.push(['finish']); return attachment; }, stop: async () => { events.push(['cancel']); } },
  };
  const module = load('MediaTools.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { View: 'View', Text: 'Text' }, './components': components, './dictionary': { errorWord: () => 'error' },
    '../runtime': { stageFile: async (_room, file) => { events.push(['stage', file]); return { ...attachment, kind: file.kind }; } },
    'react-native-image-picker': { launchImageLibrary: async () => { events.push(['picker']); return { assets: [{ uri: 'file:///picker/image.jpg', type: 'image/jpeg' }] }; } },
  });
  return { props, events, render: () => state.render(() => module.AttachmentTools(props)),
    delayStart() { props.voice.start = () => { events.push(['start']); return new Promise(resolve => { release = resolve; }); }; }, release: () => release() };
}

test('compact composer switches text/voice actions and serializes recording taps; cancel never enqueues', async () => {
  const app = composer();
  app.props.hasText = true;
  one(app.render(), 'IconButton', p => p.icon === 'send').onPress();
  assert.equal(app.events.filter(e => e[0] === 'text').length, 1);
  app.props.hasText = false; app.delayStart();
  const mic = one(app.render(), 'IconButton', p => p.icon === 'mic');
  assert.deepEqual({ width: mic.style.width, height: mic.style.height, radius: mic.style.borderRadius }, { width: 48, height: 48, radius: 24 });
  mic.onPress(); mic.onPress();
  assert.equal(app.events.filter(e => e[0] === 'start').length, 1);
  app.release(); await settled();
  app.props.voice.recording = true;
  const recording = app.render();
  assert.equal(nodes(recording).some(node => node.type === 'Field'), false);
  one(recording, 'IconButton', p => p.icon === 'close').onPress(); await settled();
  assert.equal(app.events.filter(e => e[0] === 'cancel').length, 1);
  assert.equal(app.events.filter(e => e[0] === 'attachment').length, 0);
  const stop = one(app.render(), 'IconButton', p => p.icon === 'stop');
  stop.onPress(); stop.onPress(); await settled();
  assert.equal(app.events.filter(e => e[0] === 'finish').length, 1);
  assert.equal(app.events.filter(e => e[0] === 'attachment').length, 1);
  assert.equal(app.events.find(e => e[0] === 'attachment')[1].uri, attachment.uri);
});

test('attachment panel is opt-in and uses the existing staging/enqueue flow once', async () => {
  const app = composer();
  assert.equal(nodes(app.render()).some(node => node.type === 'Button'), false);
  one(app.render(), 'IconButton', p => p.icon === 'attach').onPress();
  const photo = one(app.render(), 'Button', p => p.title === 'photo');
  photo.onPress(); photo.onPress(); await settled();
  assert.deepEqual(app.events.map(event => event[0]), ['picker', 'stage', 'attachment']);
  assert.equal(nodes(app.render()).some(node => node.type === 'Button'), false);
});

test('media withdrawal keeps text input but removes picker/mic capability; disabled composer dispatches nothing', () => {
  const app = composer();
  app.props.allowAttachments = false;
  assert.equal(nodes(app.render()).some(node => node.type === 'IconButton' && node.props.icon === 'attach'), false);
  const mic = one(app.render(), 'IconButton', p => p.icon === 'mic');
  assert.equal(mic.disabled, true); mic.onPress();
  assert.equal(app.events.length, 0);
  app.props.hasText = true;
  one(app.render(), 'IconButton', p => p.icon === 'send').onPress();
  assert.equal(app.events.length, 1);
  app.props.disabled = true;
  one(app.render(), 'IconButton', p => p.icon === 'send').onPress();
  assert.equal(app.events.length, 1);
});

function timeline(initialHidden = [], host) {
  const state = host ? { react: host.react } : hooks(); const calls = []; const voiceRights = []; const frames = []; const keyboard = {};
  const alerts = []; let hidden = [...initialHidden];
  let release;
  const tools = host?.AttachmentTools ?? function AttachmentTools() {};
  const props = { language: 'ar', t, onMenu: () => calls.push('menu'), back: () => calls.push('back'), manage: () => calls.push('members'),
    engine: { accountScope: 'actor7/epoch1', offline: false, rooms: () => [props.chat.selected], cachedHiddenMessages: () => [...hidden], hiddenMessages: async () => [...hidden],
      setMessageHidden: async (_room, id, value) => { hidden = value ? [...hidden, id] : hidden.filter(item => item !== id); calls.push(['hidden', id, value]); return [...hidden]; },
      messageInfo: async (_room, id) => { calls.push(['info', id]); return props.chat.history.messages.find(message => message.id === id); },
      enqueue: async (_room, text) => { calls.push(['text', text]); await new Promise(resolve => { release = resolve; }); }, enqueueAttachment: async () => undefined, acknowledge: async () => null },
    chat: { selected: room, presentationReady: true, offline: true, busy: false, error: null,
      identity: { user_id: 7, company_ids: [1], permissions: { chat_view: true, chat_send: true, media: true } },
      history: { messages: [{ id: 10, author_user_id: 8, author_name: 'Synthetic', text: 'retained message', created_at: '2026-10-18 12:30:00', media: { id: 1 } }] }, pending: [], capture: () => calls.push('capture'),
    },
  };
  Object.defineProperty(props.engine, 'identity', { get: () => props.chat.identity });
  const viewModel = { presentationKey: () => 'scoped', visibleReadIds: (rows, uid, active) => active ? rows.filter(row => row.message && row.message.author_user_id !== uid).map(row => row.message.id) : [], messageTime: () => '15:30', messageDateTime: () => '18/10/2026, 15:30',
    conversationAccess: (identity, selected) => {
      const canSend = !!identity?.company_ids.includes(selected.company_id) && identity.permissions.chat_view === true && identity.permissions.chat_send === true;
      return { directOff: false, canSend, canAttach: canSend && identity.permissions.media === true };
    }, canViewMedia: (identity, selected) => !!identity?.company_ids.includes(selected.company_id) && identity.permissions.chat_view === true && identity.permissions.media === true };
  const module = load('TimelineScreen.tsx', { react: state.react, 'react/jsx-runtime': host?.jsx ?? jsx,
    frames,
    'react-native': { Alert: { alert: (...args) => alerts.push(args) }, Keyboard: { addListener: (name, callback) => { keyboard[name] = callback; return { remove() {} }; } }, AppState: host?.appState ?? { currentState: 'active' }, KeyboardAvoidingView: 'KeyboardAvoidingView', Platform: { OS: 'android' }, Pressable: 'Pressable', Text: 'Text', View: 'View' },
    '../runtime': host?.runtime ?? {}, Date: host?.Date, setTimeout: host?.setTimeout, clearTimeout: host?.clearTimeout,
    '../core/ChatEngine': { ChatError: class ChatError extends Error { constructor(code) { super(code); this.code = code; } } },
    '@shopify/flash-list': { FlashList: host?.FlashList ?? 'FlashList' }, './components': components, './dictionary': { errorWord: () => 'error' }, './viewModel': viewModel,
    './MediaTools': { AttachmentTools: tools, MediaTile: 'MediaTile', PendingImagePreview: 'PendingImagePreview', useVoiceSession: (_scope, _report, play, record) => { voiceRights.push([play, record]); return { recording: false }; } },
    './GroupAvatar': { GroupAvatar: 'GroupAvatar' },
    './SwipeReply': { SwipeReply: 'SwipeReply' },
    './timelineFollow': load('timelineFollow.ts', {}),
    './companyNames': { ...require('./company-names-fixture.cjs'), identityCompanyName: () => 'Synthetic company' },
    './MessagePresentation': { MessageQuote: 'MessageQuote', MessageStatus: 'MessageStatus' },
  });
  return { props, calls, voiceRights, tools, keyboard, frames, alerts, Component: module.TimelineScreen,
    flushFrames() { for (let i = 0; i < frames.length && i < 100; i++) { const callback = frames[i]; frames[i] = null; callback?.(); } },
    render: () => state.render(() => module.TimelineScreen(props)), release: () => release() };
}

test('pending own images keep their real queued/sending Clock with scoped local preview while files/audio stay name-only', () => {
  const status = load('MessagePresentation.tsx', { react: {}, 'react/jsx-runtime': jsx, 'react-native': { View: 'View' }, './components': components }).MessageStatus;
  for (const language of ['ar', 'en']) for (const state of ['queued', 'sending']) {
    const app = timeline(); app.props.language = language;
    const item = { pending: { client_uuid: 'queued-image', room_id: room.id, company_id: room.company_id, membership_id: room.membership_id, state, text: '', attachment: { kind: 'image', name: 'own.jpg' } } };
    let row = one(app.render(), 'FlashList').renderItem({ item }); const preview = one(row, 'PendingImagePreview');
    assert.equal(preview.clientUuid, 'queued-image'); assert.equal(preview.room, room); assert.equal(preview.enabled, true);
    assert.equal(nodes(row).some(n => n.type === 'MediaTile'), false, 'no fake acknowledged media descriptor');
    assert.equal(one(status(one(row, 'MessageStatus')), 'Icon').icon, 'clock');
    app.props.chat.presentationReady = false; app.props.chat.retainedDisplay = true;
    row = one(app.render(), 'FlashList').renderItem({ item }); assert.equal(one(row, 'PendingImagePreview').enabled, false);
    for (const kind of ['audio', 'file']) {
      const other = { pending: { ...item.pending, attachment: { kind, name: kind + '.bin' } } };
      row = one(app.render(), 'FlashList').renderItem({ item: other }); assert.equal(nodes(row).some(n => n.type === 'PendingImagePreview'), false);
      assert.equal(one(row, 'Label').children, kind + '.bin');
    }
  }
});

test('actual React retains the timeline list mount, draft, reply and reader state during display-only revalidation', async () => {
  const React = require('react'), renderer = require('react-test-renderer');
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  let mounts = 0, readCount = 0, mounted;
  function FlashListProbe(props) {
    const [position, setPosition] = React.useState(() => { mounts++; return 0; });
    return React.createElement('FlashList', { ...props, fixturePosition: position, fixtureSetPosition: setPosition });
  }
  function Tools(props) { return React.createElement('AttachmentTools', props, props.children); }
  const app = timeline([], { react: React, jsx: require('react/jsx-runtime'), FlashList: FlashListProbe, AttachmentTools: Tools });
  app.props.chat.offline = false;
  app.props.engine.acknowledge = async () => { readCount++; return true; };
  const update = async () => renderer.act(async () => {
    const element = React.createElement(app.Component, app.props);
    if (!mounted) mounted = renderer.create(element); else mounted.update(element);
  });
  const get = type => mounted.root.findByType(type).props;
  try {
    await update();
    await renderer.act(async () => { get('Field').onChangeText('retained draft'); get('FlashList').fixtureSetPosition(640); });
    // Exercise the real reply handler through its SwipeReply callback.
    const item = get('FlashList').data[0];
    await renderer.act(async () => get('FlashList').renderItem({ item }).props.onReply());
    assert.equal(get('MessageQuote').text, 'retained message');
    const list = get('FlashList'), send = get('AttachmentTools').onSendText;
    const pendingItem = { key: 'pending', pending: { client_uuid: 'fixture', text: '', attachment: { name: 'queued.jpg' }, state: 'queued' } };
    const originalPending = one(list.renderItem({ item: pendingItem }), 'Label', p => p.children === 'queued.jpg');
    app.props.chat.presentationReady = false; app.props.chat.retainedDisplay = true; app.props.presented = false;
    await update();
    assert.equal(mounts, 1); assert.equal(get('FlashList').fixturePosition, 640);
    assert.equal(get('Field').value, 'retained draft'); assert.equal(get('MessageQuote').text, 'retained message');
    assert.equal(get('GroupAvatar').enabled, false); assert.deepEqual(app.voiceRights.at(-1), [false, false]);
    const imageRow = get('FlashList').renderItem({ item: { ...item, message: { ...item.message, media: { kind: 'image', name: 'private.jpg' } } } });
    assert.equal(one(imageRow, 'View', p => p.testID === 'retained-image-space').style.height, 180);
    assert.equal(nodes(imageRow).some(row => row.type === 'MediaTile'), false);
    const audioRow = get('FlashList').renderItem({ item: { ...item, message: { ...item.message, media: { kind: 'audio' } } } });
    assert.equal(one(audioRow, 'View', p => p.testID === 'retained-audio-space').style.minHeight, 60);
    assert.equal(get('Field').editable, false); assert.equal(get('AttachmentTools').disabled, true);
    assert.deepEqual(one(get('FlashList').renderItem({ item: pendingItem }), 'Label', p => p.children === 'queued.jpg'), originalPending,
      'queued attachments retain their existing name-only geometry without starting media work');
    await renderer.act(async () => {
      send(); list.onViewableItemsChanged({ viewableItems: [{ isViewable: true, item }] });
      list.viewabilityConfigCallbackPairs[0].onViewableItemsChanged({ viewableItems: [{ isViewable: true, item }] });
    });
    assert.equal(readCount, 0); assert.equal(app.calls.length, 0);
    app.props.chat.presentationReady = true; app.props.presented = true;
    await update();
    assert.equal(mounts, 1); assert.equal(get('FlashList').fixturePosition, 640);
    assert.equal(get('Field').value, 'retained draft'); assert.equal(get('MessageQuote').text, 'retained message');
  } finally { await renderer.act(async () => mounted?.unmount()); }
});

async function pickerTimeline({ delayStage = false, offline = false, kind = 'image' } = {}) {
  const React = require('react'), renderer = require('react-test-renderer');
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  let mounted, pickResult, stageResult, time = 1000000;
  const events = [], timers = new Set(), appState = { currentState: 'active' };
  const runtime = {
    stageFile: async (_room, input) => {
      events.push(['stage', input]);
      return delayStage ? new Promise(resolve => { stageResult = resolve; }) : { ...attachment, kind: input.kind, mime: input.mime, name: input.name };
    },
    discardStagedAttachment: async value => events.push(['discard', value]),
  };
  const actualTools = load('MediaTools.tsx', { react: React, 'react/jsx-runtime': require('react/jsx-runtime'),
    'react-native': { View: 'View', Platform: { OS: 'android' }, PermissionsAndroid: {}, AppState: appState },
    './components': components, './dictionary': { errorWord: () => 'error' }, '../runtime': runtime,
    '@react-native-documents/picker': { pick: () => new Promise(resolve => { pickResult = resolve; }),
      types: { pdf: 'pdf', plainText: 'text', docx: 'docx', xlsx: 'xlsx' }, isErrorWithCode: () => false, errorCodes: { OPERATION_CANCELED: 'cancelled' } },
    'react-native-image-picker': { launchImageLibrary: () => new Promise(resolve => { pickResult = resolve; }), launchCamera: async () => ({ didCancel: true }) },
  }).AttachmentTools;
  const app = timeline([], { react: React, jsx: require('react/jsx-runtime'), AttachmentTools: actualTools, runtime, appState,
    Date: { now: () => time }, setTimeout: callback => { timers.add(callback); return callback; }, clearTimeout: callback => timers.delete(callback),
  });
  app.props.engine.accountScope = 'actor7/epoch1'; app.props.engine.offline = offline;
  app.props.chat.offline = offline; app.props.chat.sync = async () => events.push(['sync']);
  app.props.engine.enqueueAttachment = async (...args) => events.push(['enqueue', ...args]);
  const update = async () => renderer.act(async () => {
    const element = React.createElement(app.Component, app.props);
    if (mounted) mounted.update(element); else mounted = renderer.create(element);
  });
  const get = (type, match) => mounted.root.findAllByType(type).find(node => !match || match(node.props)).props;
  return { ...app, events, appState, get, update, act: renderer.act,
    async start() {
    await update();
    await renderer.act(async () => get('IconButton', p => p.icon === 'attach').onPress());
    await renderer.act(async () => get('Button', p => p.title === (kind === 'file' ? 'file' : 'photo')).onPress());
    },
    async pause() {
      app.props.chat.presentationReady = false; app.props.chat.retainedDisplay = true; app.props.presented = false;
      app.props.chat.offline = true; app.props.engine.offline = true; appState.currentState = 'background'; await update();
    },
    async resume() {
      appState.currentState = 'active'; app.props.chat.presentationReady = true; app.props.presented = true;
      app.props.chat.offline = offline; app.props.engine.offline = offline; await update(); await settled();
    },
    async picked(value = kind === 'file' ? [{ uri: 'content://picker/document.pdf', name: 'document.pdf', type: 'application/pdf' }]
      : { assets: [{ uri: 'file:///picker/image.jpg', type: 'image/jpeg' }] }) {
      await renderer.act(async () => { pickResult(value); await settled(); });
    },
    async releaseStage() { await renderer.act(async () => { stageResult({ ...attachment, kind: 'image' }); await settled(); }); },
    async expire() { time += 300001; await renderer.act(async () => { for (const callback of [...timers]) callback(); await settled(); }); },
    async unmount() { await renderer.act(async () => mounted?.unmount()); },
  };
}

test('actual picker return waits through foreground revalidation then enqueues its selected attachment exactly once', async () => {
  for (const kind of ['image', 'file']) {
  const app = await pickerTimeline({ kind });
  try {
    await app.start(); await app.pause(); app.appState.currentState = 'active'; await app.picked();
    assert.equal(app.events.length, 0, 'no staging, upload or enqueue while original authority is being revalidated');
    await app.resume();
    assert.equal(app.events.filter(event => event[0] === 'stage').length, 1);
    assert.equal(app.events.find(event => event[0] === 'stage')[1].kind, kind);
    assert.equal(app.events.filter(event => event[0] === 'enqueue').length, 1);
    await app.update(); assert.equal(app.events.filter(event => event[0] === 'enqueue').length, 1);
  } finally { await app.unmount(); }
  }
});

test('actual picker retains its original draft/reply and does not clear a newer draft after local enqueue', async () => {
  const app = await pickerTimeline({ delayStage: true });
  try {
    await app.update();
    await app.act(async () => app.get('Field').onChangeText('original caption'));
    await app.act(async () => { const list = app.get('FlashList'); list.renderItem({ item: list.data[0] }).props.onReply(); });
    await app.start(); await app.pause(); app.appState.currentState = 'active'; await app.picked(); await app.resume();
    await app.act(async () => { app.get('Field').onChangeText('newer draft'); app.get('IconButton', p => p.label === 'cancel').onPress(); });
    await app.releaseStage();
    const enqueued = app.events.filter(event => event[0] === 'enqueue');
    assert.equal(enqueued.length, 1); assert.equal(enqueued[0][3], 'original caption'); assert.equal(enqueued[0][4], 10);
    assert.equal(app.get('Field').value, 'newer draft');
    assert.equal(app.events.some(event => event[0] === 'discard'), false, 'durable enqueue owns its stage exclusively');
  } finally { await app.unmount(); }
});

test('actual offline picker keeps bounded local enqueue and never requests sync; expired local authority cancels', async () => {
  const app = await pickerTimeline({ offline: true });
  try {
    await app.start(); await app.picked();
    assert.equal(app.events.filter(event => event[0] === 'enqueue').length, 1);
    assert.equal(app.events.filter(event => event[0] === 'sync').length, 0);
    await app.start(); app.props.engine.rooms = () => { throw new Error('offline_expired'); };
    await app.picked();
    assert.equal(app.events.filter(event => event[0] === 'enqueue').length, 1);
    assert.equal(app.events.filter(event => event[0] === 'stage').length, 1);
  } finally { await app.unmount(); }
});

test('actual selected picker cancels before staging after actor/company/membership/grant change, expiry or unmount', async () => {
  for (const changed of ['actor', 'companies', 'room', 'membership', 'grant', 'revision', 'expiry', 'unmount', 'picker_cancel']) {
    const app = await pickerTimeline();
    try {
      await app.start(); await app.pause();
      if (changed === 'actor') app.props.engine.accountScope = 'actor7/epoch2';
      if (changed === 'companies') app.props.chat.identity = { ...app.props.chat.identity, company_ids: [1, 2] };
      if (changed === 'room') app.props.chat.selected = { ...room, id: 5 };
      if (changed === 'membership') app.props.chat.selected = { ...room, membership_id: 10 };
      if (changed === 'grant') app.props.chat.identity = { ...app.props.chat.identity, permissions: { ...app.props.chat.identity.permissions, media: false } };
      if (changed === 'revision') app.props.chat.identity = { ...app.props.chat.identity, permissions: { ...app.props.chat.identity.permissions, revision: 2 } };
      if (changed === 'expiry') await app.expire();
      if (changed === 'unmount') await app.unmount();
      app.appState.currentState = 'active'; await app.picked(changed === 'picker_cancel' ? { didCancel: true } : undefined);
      if (changed !== 'unmount') await app.resume();
      assert.equal(app.events.filter(event => ['stage', 'enqueue', 'sync'].includes(event[0])).length, 0, changed);
    } finally { if (changed !== 'unmount') await app.unmount(); }
  }
});

test('cancellation during a pending stage discards the late unclaimed file once and never enqueues it', async () => {
  const app = await pickerTimeline({ delayStage: true });
  try {
    await app.start(); await app.picked();
    app.props.engine.accountScope = 'actor8/epoch2'; await app.update();
    await app.releaseStage();
    assert.equal(app.events.filter(event => event[0] === 'enqueue').length, 0);
    assert.equal(app.events.filter(event => event[0] === 'discard').length, 1);
  } finally { await app.unmount(); }
});

test('selected attachment enqueue failure is attempted once and never automatically retried or discarded by the picker', async () => {
  const app = await pickerTimeline();
  app.props.engine.enqueueAttachment = async (...args) => { app.events.push(['enqueue', ...args]); throw new Error('synthetic uncertain enqueue'); };
  try {
    await app.start(); await app.picked(); await app.update(); await app.update();
    assert.equal(app.events.filter(event => event[0] === 'enqueue').length, 1);
    assert.equal(app.events.filter(event => event[0] === 'discard').length, 0, 'claimed files belong exclusively to native outbox cleanup');
    assert.equal(app.events.filter(event => event[0] === 'sync').length, 0);
  } finally { await app.unmount(); }
});
test('archive controls navigate cached pages offline and durable sends do not snap a browsing timeline', async () => {
  const app = timeline(); let scrolls = 0;
  app.props.chat.history.next_before_id = 10;
  app.props.chat.history.archive = { browsing: true, partial: true, older: { kind: 'cached', cursor: 10 }, newer: { kind: 'cached', cursor: 10 } };
  app.props.chat.older = async () => app.calls.push('older');
  app.props.chat.newer = async () => app.calls.push('newer');
  app.props.chat.latest = async () => app.calls.push('latest');
  let tree = app.render(); let list = one(tree, 'FlashList');
  list.ref.current = { scrollToEnd: () => scrolls++ }; app.flushFrames();
  const older = one(list.ListHeaderComponent, 'Button'); assert.equal(older.disabled, false); older.onPress();
  assert.equal(one(list.ListHeaderComponent, 'Label').children, 'archiveGap');
  one(list.ListFooterComponent, 'Button').onPress();
  one(tree, 'Field').onChangeText('keep reader position'); tree = app.render();
  one(tree, app.tools).onSendText(); app.release(); await settled(); app.render(); app.flushFrames();
  assert.equal(scrolls, 0); assert.equal(one(app.render(), 'Field').value, '');
  one(app.render(), 'IconButton', props => props.icon === 'down').onPress(); await settled();
  assert.ok(app.calls.includes('older')); assert.ok(app.calls.includes('newer')); assert.ok(app.calls.includes('latest'));
  app.props.chat.history.archive.older.kind = 'gap'; list = one(app.render(), 'FlashList');
  assert.equal(one(list.ListHeaderComponent, 'Button').disabled, true, 'offline gap is not presented as cached or complete');
});

test('send feedback occurs once only after a successful durable enqueue, not the initial tap or a failed retry', async () => {
  const app = timeline(); app.props.chat.soundSent = () => app.calls.push('sound');
  one(app.render(), 'Field').onChangeText('accepted');
  const press = one(app.render(), app.tools).onSendText;
  press(); press(); await settled(); assert.equal(app.calls.includes('sound'), false);
  app.release(); await settled(); assert.equal(app.calls.filter(value => value === 'sound').length, 1);
  app.props.engine.enqueue = async () => { throw new Error('synthetic failure'); };
  one(app.render(), 'Field').onChangeText('retry'); one(app.render(), app.tools).onSendText(); await settled();
  assert.equal(app.calls.filter(value => value === 'sound').length, 1);
  assert.equal(one(app.render(), 'GroupAvatar').enabled, true);
});

test('Android composer avoidance uses the measured screen offset and ignores an older layout measurement', () => {
  const app = timeline();
  const tree = app.render();
  const callbacks = [];
  tree.props.ref.current = { measureInWindow: callback => callbacks.push(callback) };
  tree.props.onLayout(); tree.props.onLayout();
  callbacks[1](0, 84); callbacks[0](0, 24);
  const avoidance = one(app.render(), 'KeyboardAvoidingView');
  assert.equal(avoidance.behavior, 'height');
  assert.equal(avoidance.keyboardVerticalOffset, 84);
});

test('conversation menu occupies the same leading physical language edge as inbox, with Back opposite', () => {
  const app = timeline();
  for (const language of ['ar', 'en']) {
    app.props.language = language; const tree = app.render();
    const menu = nodes(tree).find(node => node.type === 'IconButton' && node.props.icon === 'menu');
    const header = nodes(tree).find(node => Array.isArray(node.props?.children) && node.props.children.includes(menu));
    const children = header.props.children.filter(Boolean);
    assert.equal(children[0], menu);
    assert.equal(children.at(-1).props.icon, 'back');
    assert.equal(header.props.style.at(-1).flexDirection, language === 'ar' ? 'row-reverse' : 'row');
    assert.equal(header.props.style.at(-1).direction, 'ltr');
  }
});

test('only viewport-visible authorized image rows request automatic previews, separate from read receipts', () => {
  const app = timeline(); let tree = app.render();
  const row = { key: 'message-10', message: app.props.chat.history.messages[0] };
  row.message.media.kind = 'image';
  let list = one(tree, 'FlashList');
  assert.equal(one(list.renderItem({ item: row }), 'MediaTile').previewVisible, false);
  assert.equal(list.viewabilityConfig.minimumViewTime, 600, 'read receipt dwell unchanged');
  const preview = list.viewabilityConfigCallbackPairs[0];
  assert.equal(preview.viewabilityConfig.itemVisiblePercentThreshold, 10);
  preview.onViewableItemsChanged({ viewableItems: [{ isViewable: true, item: row }] });
  tree = app.render(); list = one(tree, 'FlashList');
  assert.equal(one(list.renderItem({ item: row }), 'MediaTile').previewVisible, true);
  list.viewabilityConfigCallbackPairs[0].onViewableItemsChanged({ viewableItems: [] });
  list = one(app.render(), 'FlashList');
  assert.equal(one(list.renderItem({ item: row }), 'MediaTile').previewVisible, false);
  app.props.chat.identity.permissions.media = false;
  assert.equal(nodes(one(app.render(), 'FlashList').renderItem({ item: row })).some(n => n.type === 'MediaTile'), false);
});

test('pending image ACK at the same visible index recomputes actual FlashList viewability without a scroll', () => {
  // Use the installed library's index-only change detector, not a mock that
  // invents an ACK callback the real native list does not emit.
  const { default: ViewabilityHelper } = load('../../../node_modules/@shopify/flash-list/src/recyclerview/viewability/ViewabilityHelper.ts', {
    '../../errors/ErrorMessages': { ErrorMessages: {} },
  });
  const app = timeline(); app.props.chat.history.messages = [];
  app.props.chat.pending = [{ client_uuid: 'same-slot', room_id: room.id, company_id: room.company_id,
    membership_id: room.membership_id, state: 'queued', text: '', attachment: { kind: 'image', name: 'new.jpg' } }];
  let list = one(app.render(), 'FlashList'), callbacks = 0, recomputes = 0;
  const helper = new ViewabilityHelper({ minimumViewTime: 0, itemVisiblePercentThreshold: 10 }, indices => {
    callbacks++;
    list.viewabilityConfigCallbackPairs[0].onViewableItemsChanged({ viewableItems: indices.map(index => ({ index, isViewable: true, item: list.data[index] })) });
  });
  const update = () => helper.updateViewableItems(false, 0, { width: 320, height: 640 }, () => ({ x: 0, y: 0, width: 280, height: 180 }), [0]);
  list.ref.current = { scrollToEnd() {}, recomputeViewableItems() { recomputes++; helper.clearLastReportedViewableIndices(); update(); } };
  update(); app.flushFrames(); list = one(app.render(), 'FlashList');
  const initial = callbacks;
  app.props.chat.pending = [];
  app.props.chat.history.messages = [{ id: 77, author_user_id: 7, text: '', created_at: '', media: { id: 177, kind: 'image' } }];
  list = one(app.render(), 'FlashList'); update();
  assert.equal(callbacks, initial, 'same visible index alone does not emit an ACK row callback');
  assert.equal(one(list.renderItem({ item: list.data[0] }), 'MediaTile').previewVisible, false);
  app.flushFrames(); list = one(app.render(), 'FlashList');
  assert.equal(one(list.renderItem({ item: list.data[0] }), 'MediaTile').previewVisible, true,
    'ACK image must be discovered without moving the viewport');
  const before = recomputes;
  app.props.chat.history.messages = app.props.chat.history.messages.map(row => ({ ...row }));
  app.render(); app.flushFrames(); assert.equal(recomputes, before, 'identical history polls must not reset viewability');
  helper.dispose();
});

test('deferred preview discovery rejects hidden unverified revoked and old-account frames', () => {
  for (const change of [app => { app.props.presented = false; },
    app => { app.props.chat.presentationReady = false; app.props.chat.retainedDisplay = true; },
    app => { app.props.chat.identity.permissions.media = false; },
    app => { app.props.engine.accountScope = 'actor8/epoch2'; }]) {
    const app = timeline(); let count = 0;
    const list = one(app.render(), 'FlashList');
    list.ref.current = { scrollToEnd() {}, recomputeViewableItems() { count++; } };
    const stale = app.frames.filter(Boolean);
    change(app); app.render();
    // Even a callback already handed to native cannot use old presentation.
    for (const callback of stale) callback();
    assert.equal(count, 0);
  }
  const app = timeline(); app.props.presented = false; let count = 0;
  const list = one(app.render(), 'FlashList'); list.ref.current = { recomputeViewableItems() { count++; } };
  app.flushFrames(); assert.equal(count, 0);
});

test('timeline gives history the remaining height, caps inline input and dispatches a draft only once before durable enqueue', async () => {
  const app = timeline();
  let tree = app.render();
  assert.equal(one(tree, 'KeyboardAvoidingView').style[1].minHeight, 0);
  const list = one(tree, 'FlashList');
  assert.equal(nodes(tree).find(node => node.type === 'View' && nodes(node.props.children).some(child => child.type === 'FlashList') && node.props.style?.flex === 1).props.style.flex, 1);
  assert.equal(list.viewabilityConfig.minimumViewTime, 600);
  assert.equal(list.viewabilityConfig.viewAreaCoveragePercentThreshold, 75);
  const field = one(tree, 'Field');
  assert.equal(field.style.minWidth, 0); assert.equal(field.style.maxHeight, 120);
  field.onChangeText('new draft'); tree = app.render();
  const composer = one(tree, app.tools);
  composer.onSendText(); composer.onSendText();
  assert.equal(app.calls.filter(call => Array.isArray(call) && call[0] === 'text').length, 1);
  assert.equal(app.calls[0][1], 'new draft');
  assert.equal(one(app.render(), 'Field').value, 'new draft');
  app.release(); await settled();
  assert.equal(one(app.render(), 'Field').value, '');
  one(tree, 'IconButton', p => p.icon === 'menu').onPress();
  assert.ok(app.calls.includes('menu'));
});

test('typing preserves timeline data and cell presentation identity while local actions explicitly invalidate cells', async () => {
  const app = timeline(); app.render(); await settled();
  const first = one(app.render(), 'FlashList');
  one(app.render(), 'Field').onChangeText('a draft'); const typed = one(app.render(), 'FlashList');
  assert.equal(typed.data, first.data); assert.equal(typed.extraData, first.extraData);
  one(typed.renderItem({ item: typed.data[0] }), 'Pressable').onPress();
  const actions = one(app.render(), 'FlashList'); assert.equal(actions.data, first.data); assert.notEqual(actions.extraData, typed.extraData);
});

test('timeline hides retained rows during blocked or wrong-company presentation and passes revoked rights into voice', () => {
  const app = timeline(); app.render();
  app.props.chat.presentationReady = false;
  assert.equal(app.render(), null);
  assert.deepEqual(app.voiceRights.at(-1), [false, false]);
  app.props.chat.presentationReady = true; app.props.chat.identity.company_ids = [2];
  assert.equal(app.render(), null);
  app.props.chat.identity.company_ids = [1]; app.props.chat.identity.permissions.chat_view = false;
  assert.equal(app.render(), null);
  app.props.chat.identity.permissions.chat_view = true; app.props.chat.identity.permissions.media = false;
  const visible = app.render();
  assert.equal(one(visible, app.tools).allowAttachments, false);
  const row = one(visible, 'FlashList').renderItem({ item: { message: app.props.chat.history.messages[0] } });
  assert.equal(nodes(row).some(node => node.type === 'MediaTile'), false);
  app.props.chat.identity.permissions.chat_send = false;
  assert.equal(nodes(app.render()).some(node => node.type === app.tools), false);
  assert.deepEqual(app.voiceRights.at(-1), [false, false]);
});

test('hidden retained conversation fences read media voice and old callbacks while preserving draft reply and reader geometry', async () => {
  const app = timeline(); app.props.chat.offline = false;
  app.props.chat.history.messages[0].media.kind = 'image';
  let releaseInfo, releaseRead, readCount = 0, scrolls = 0;
  app.props.engine.messageInfo = () => new Promise(resolve => { releaseInfo = resolve; });
  app.props.engine.acknowledge = () => { readCount++; return new Promise(resolve => { releaseRead = resolve; }); };
  let tree = app.render(); await settled(); tree = app.render();
  const list = one(tree, 'FlashList');
  list.ref.current = { scrollToEnd: () => scrolls++ };
  app.flushFrames();
  list.onScroll({nativeEvent: {contentSize: {height: 2000}, layoutMeasurement: {height: 500}, contentOffset: {y: 1500}}});
  const item = list.data[0]; const viewable = {viewableItems: [{isViewable: true, item}]};
  list.viewabilityConfigCallbackPairs[0].onViewableItemsChanged(viewable);
  list.onViewableItemsChanged(viewable); assert.equal(readCount, 1);
  const field = one(tree, 'Field'); field.onChangeText('preserved draft');
  const message = one(list.renderItem({item}), 'Pressable'); message.onLongPress();
  tree = app.render(); one(one(tree, 'FlashList').renderItem({item}), 'Pressable').onPress();
  tree = app.render(); const actions = one(tree, 'FlashList').renderItem({item});
  const oldInfo = one(actions, 'IconButton', p => p.icon === 'info').onPress;
  oldInfo(); tree = app.render(); assert.ok(one(tree, 'Sheet'));
  const oldSend = one(tree, app.tools).onSendText;
  const oldMenu = one(tree, 'IconButton', p => p.icon === 'menu').onPress;
  const oldBack = one(tree, 'IconButton', p => p.icon === 'back').onPress;
  const oldMembers = one(tree, 'IconButton', p => p.icon === 'members').onPress;
  const measured = []; tree.props.ref.current = { measureInWindow: callback => measured.push(callback) };
  tree.props.onLayout();
  const priorScrolls = scrolls;
  app.props.presented = false; app.render(); tree = app.render();
  assert.deepEqual(app.voiceRights.at(-1), [false, false]);
  assert.equal(one(tree, 'GroupAvatar').enabled, false);
  assert.equal(nodes(one(tree, 'FlashList').renderItem({item})).some(n => n.type === 'MediaTile'), false);
  assert.equal(nodes(tree).some(n => n.type === 'Sheet'), false);
  const hiddenViewable = {viewableItems: [{isViewable: true, item: {message: {...item.message, id: 11}}}]};
  list.onViewableItemsChanged(hiddenViewable);
  list.viewabilityConfigCallbackPairs[0].onViewableItemsChanged(viewable);
  field.onChangeText('must not overwrite hidden draft'); oldSend(); oldInfo(); oldMenu(); oldBack(); oldMembers();
  measured[0](0, 900);
  tree.props.onLayout(); assert.equal(measured.length, 1, 'hidden root never requests a zero-sized layout measurement');
  list.onScrollBeginDrag(); list.onMomentumScrollBegin();
  list.onScroll({nativeEvent: {contentSize: {height: 0}, layoutMeasurement: {height: 0}, contentOffset: {y: 0}}});
  list.onLayout({nativeEvent: {layout: {height: 0}}}); list.onContentSizeChange(0, 0);
  list.onScrollEndDrag(); list.onMomentumScrollEnd(); app.keyboard.keyboardDidHide(); app.flushFrames();
  releaseInfo(item.message); releaseRead(true); await settled();
  assert.equal(readCount, 1, 'late native viewability cannot mark a hidden message read');
  assert.equal(app.calls.length, 0, 'hidden callbacks perform no enqueue, navigation, capture or message operation');
  assert.equal(scrolls, priorScrolls);
  app.props.presented = true; tree = app.render(); await settled(); tree = app.render();
  assert.deepEqual(app.voiceRights.at(-1), [true, true]);
  assert.equal(one(tree, 'Field').value, 'preserved draft');
  assert.equal(one(tree, 'MessageQuote').text, 'retained message');
  assert.equal(nodes(tree).some(n => n.type === 'Sheet'), false, 'old async information cannot reopen after returning');
  assert.equal(one(tree, 'KeyboardAvoidingView').keyboardVerticalOffset, 0, 'late old measurement is discarded');
  const restoredList = one(tree, 'FlashList');
  assert.equal(one(restoredList.renderItem({item}), 'MediaTile').previewVisible, false);
  assert.equal(nodes(restoredList.renderItem({item})).some(n => n.type === 'IconButton'), false, 'message action strip stays closed');
  app.keyboard.keyboardDidShow(); app.flushFrames();
  assert.equal(scrolls, priorScrolls, 'restored aligned geometry was not overwritten by hidden zero-sized events');
});

test('durable enqueue finishing behind Orders clears only its accepted draft without hidden send tone or scrolling', async () => {
  for (const outcome of ['accepted', 'newer-draft', 'revoked', 'changed-scope']) {
    const app = timeline(); let scrolls = 0;
    app.props.chat.soundSent = () => app.calls.push('sent-tone');
    let tree = app.render();
    const list = one(tree, 'FlashList'); list.ref.current = {scrollToEnd: () => scrolls++}; app.flushFrames();
    one(list.renderItem({item: list.data[0]}), 'Pressable').onLongPress();
    one(app.render(), 'Field').onChangeText('accepted draft');
    tree = app.render(); one(tree, app.tools).onSendText();
    if (outcome === 'newer-draft') one(app.render(), 'Field').onChangeText('newer draft');
    app.props.presented = false;
    if (outcome === 'revoked') app.props.chat.identity.permissions.chat_send = false;
    if (outcome === 'changed-scope') app.props.engine.accountScope = 'different-actor';
    app.render(); const before = scrolls;
    app.release(); await settled(); app.flushFrames();
    assert.equal(app.calls.filter(call => Array.isArray(call) && call[0] === 'text').length, 1);
    assert.equal(app.calls.includes('sent-tone'), false); assert.equal(scrolls, before);
    assert.equal(app.calls.filter(call => call === 'capture').length, ['accepted', 'newer-draft'].includes(outcome) ? 1 : 0);
    app.props.presented = true; app.props.chat.identity.permissions.chat_send = true;
    tree = app.render();
    assert.equal(one(tree, 'Field').value, outcome === 'accepted' ? '' : outcome === 'newer-draft' ? 'newer draft' : 'accepted draft', outcome);
    assert.equal(nodes(tree).some(node => node.type === 'MessageQuote'), ['revoked', 'changed-scope'].includes(outcome), outcome);
  }
});

test('accepted local hide behind Orders settles only the latest authorized mutation without resurrecting message actions', async () => {
  for (const outcome of ['accepted', 'revoked', 'changed-scope', 'newer-mutation', 'late-old-read']) {
    const app = timeline(); const pending = []; let releaseOldRead;
    app.props.chat.history.messages[0].author_user_id = 7;
    app.props.chat.history.messages.push({id: 11, author_user_id: 7, text: 'second own message'});
    if (outcome === 'late-old-read') app.props.engine.hiddenMessages = () => new Promise(resolve => { releaseOldRead = resolve; });
    app.props.engine.setMessageHidden = (_room, id) => new Promise(resolve => pending.push({id, resolve}));
    app.render(); await settled();
    const hide = id => {
      const list = one(app.render(), 'FlashList'); const item = list.data.find(row => row.message?.id === id);
      one(list.renderItem({item}), 'Pressable').onAccessibilityAction({nativeEvent: {actionName: 'hide'}});
      app.alerts.at(-1)[2].find(button => button.style === 'destructive').onPress();
    };
    hide(10); assert.equal(pending.length, 1);
    app.props.presented = false;
    if (outcome === 'revoked') app.props.chat.identity.permissions.chat_view = false;
    if (outcome === 'changed-scope') app.props.engine.accountScope = 'new actor';
    app.render();
    if (outcome === 'newer-mutation') {
      app.props.presented = true; app.render(); hide(11);
      pending[1].resolve([11]); await settled();
      app.props.presented = false; app.render();
    }
    pending[0].resolve([10]); await settled();
    if (releaseOldRead) { releaseOldRead([]); await settled(); }
    assert.equal(app.calls.length, 0, 'hidden settlement has no capture, navigation, playback or scroll side effect');
    app.props.chat.identity.permissions.chat_view = true; app.props.presented = true;
    const tree = app.render(); const list = one(tree, 'FlashList');
    const first = JSON.stringify(list.renderItem({item: list.data[0]}));
    const firstHidden = ['accepted', 'late-old-read'].includes(outcome);
    assert.equal(first.includes('locallyHidden'), firstHidden, outcome);
    assert.equal(first.includes('retained message'), !firstHidden, outcome);
    if (outcome === 'newer-mutation') assert.equal(JSON.stringify(list.renderItem({item: list.data[1]})).includes('locallyHidden'), true);
    assert.equal(nodes(tree).some(node => node.type === 'Sheet'), false);
    assert.equal(nodes(list.renderItem({item: list.data[0]})).some(node => node.type === 'IconButton'), false);
  }
});

test('a rejected durable enqueue preserves the draft and releases the UI lock for a deliberate retry', async () => {
  const app = timeline();
  let attempts = 0;
  app.props.engine.enqueue = async () => { attempts++; throw new Error('synthetic storage failure'); };
  one(app.render(), 'Field').onChangeText('retain this draft');
  one(app.render(), app.tools).onSendText(); await settled();
  assert.equal(one(app.render(), 'Field').value, 'retain this draft');
  one(app.render(), app.tools).onSendText(); await settled();
  assert.equal(attempts, 2);
  assert.equal(app.calls.includes('capture'), false);
});

test('actual list follows keyboard/viewport/composer changes and durable own sends, without dismissing keyboard', async () => {
  const app = timeline(); let tree = app.render(); let scrolls = 0;
  one(tree, 'FlashList').ref.current = { scrollToEnd: options => { assert.equal(options.animated, false); scrolls++; } };
  app.flushFrames(); const initial = scrolls;
  app.keyboard.keyboardDidShow(); app.flushFrames(); assert.ok(scrolls > initial);
  const beforeResize = scrolls;
  one(tree, 'FlashList').onLayout(); one(tree, 'Field').onContentSizeChange(); app.flushFrames();
  assert.ok(scrolls > beforeResize);
  one(tree, 'Field').onChangeText('visible above keyboard'); tree = app.render();
  one(tree, app.tools).onSendText(); app.release(); await settled(); app.render(); app.flushFrames();
  assert.equal(one(app.render(), 'Field').value, '');
  assert.ok(scrolls >= beforeResize + 2, 'one resize correction and one durable-send correction');
  assert.equal(one(app.render(), 'FlashList').keyboardShouldPersistTaps, 'handled');
});

test('history reader is not pulled by incoming messages, prepends, or keyboard; latest action and own sends opt in', async () => {
  const app = timeline(); let tree = app.render(); let scrolls = 0;
  one(tree, 'FlashList').ref.current = { scrollToEnd: () => scrolls++ }; app.flushFrames();
  const list = one(tree, 'FlashList');
  list.onScrollBeginDrag();
  list.onScroll({ nativeEvent: { contentSize: { height: 2000 }, layoutMeasurement: { height: 500 }, contentOffset: { y: 400 } } });
  list.onScrollEndDrag(); const start = scrolls;
  app.props.chat.history.messages.push({ id: 11, author_user_id: 8, author_name: 'Other', text: 'incoming' });
  app.render(); app.flushFrames(); app.keyboard.keyboardDidShow(); app.flushFrames();
  assert.equal(scrolls, start);
  app.props.chat.history.messages.unshift({ id: 1, author_user_id: 8, text: 'older page' });
  tree = app.render(); one(tree, 'FlashList').onContentSizeChange(); app.flushFrames(); assert.equal(scrolls, start);
  one(tree, 'IconButton', p => p.icon === 'down').onPress(); app.flushFrames(); assert.ok(scrolls > start);
});

test('IME geometry onScroll arriving before keyboard/onLayout cannot opt out of bottom following', () => {
  const app = timeline(); const tree = app.render(); let scrolls = 0;
  const list = one(tree, 'FlashList'); list.ref.current = { scrollToEnd: () => scrolls++ };
  app.flushFrames();
  list.onScroll({ nativeEvent: { contentSize: { height: 2000 }, layoutMeasurement: { height: 600 }, contentOffset: { y: 1400 } } });
  list.onScroll({ nativeEvent: { contentSize: { height: 2000 }, layoutMeasurement: { height: 350 }, contentOffset: { y: 1400 } } });
  const before = scrolls;
  list.onLayout(); app.keyboard.keyboardDidShow(); app.flushFrames();
  assert.ok(scrolls > before);
  list.onScrollBeginDrag();
  list.onScroll({ nativeEvent: { contentSize: { height: 2000 }, layoutMeasurement: { height: 350 }, contentOffset: { y: 1000 } } });
  list.onScrollEndDrag(); list.onMomentumScrollBegin();
  list.onScroll({ nativeEvent: { contentSize: { height: 2000 }, layoutMeasurement: { height: 350 }, contentOffset: { y: 700 } } });
  list.onMomentumScrollEnd(); const reader = scrolls;
  // Keyboard hide grows viewport enough to expose the tail. That is not reader intent.
  list.onScroll({ nativeEvent: { contentSize: { height: 2000 }, layoutMeasurement: { height: 1300 }, contentOffset: { y: 700 } } });
  app.keyboard.keyboardDidShow(); list.onContentSizeChange(); app.flushFrames();
  assert.equal(scrolls, reader);
});

test('reply uses contextual affordance, focuses input and retains quote on failed enqueue; receipt cluster has no permanent reply', async () => {
  const app = timeline(); let tree = app.render(); let focus = 0;
  one(tree, 'Field').ref.current = { focus: () => focus++ };
  let row = one(tree, 'FlashList').renderItem({ item: { key: 'message-10', message: app.props.chat.history.messages[0] } });
  assert.equal(nodes(row).some(n => n.type === 'IconButton' && n.props.icon === 'reply'), false);
  one(row, 'Pressable').onPress(); tree = app.render();
  row = one(tree, 'FlashList').renderItem({ item: { key: 'message-10', message: app.props.chat.history.messages[0] } });
  one(row, 'IconButton', p => p.icon === 'reply').onPress(); tree = app.render();
  assert.equal(focus, 1); assert.equal(one(tree, 'MessageQuote').text, 'retained message');
  app.props.engine.enqueue = async () => { throw Error('storage'); };
  one(tree, 'Field').onChangeText('keep draft'); one(app.render(), app.tools).onSendText(); await settled();
  assert.equal(one(app.render(), 'MessageQuote').text, 'retained message');
  assert.equal(one(app.render(), 'Field').value, 'keep draft');
});

test('server retention tombstones render explicit bodies and full removal cannot start a reply while media-only text remains replyable',()=>{
 const dictionary=load('dictionary.ts',{});
 assert.equal(dictionary.translator('ar')('contentRemoved'),'حُذف المحتوى');assert.equal(dictionary.translator('ar')('mediaRemoved'),'حُذف المرفق');
 assert.equal(dictionary.translator('en')('contentRemoved'),'Content removed');assert.equal(dictionary.translator('en')('mediaRemoved'),'Attachment removed');
 for(const language of ['ar','en'])for(const mode of ['content','empty-media','caption-media']){
  const app=timeline();app.props.language=language;
  app.props.chat.history.messages=[{id:10,author_user_id:8,author_name:'Synthetic',created_at:'2026-10-20 10:00:00',text:mode==='caption-media'?'caption survives':'',...(mode==='content'?{content_removed:true}:{media_removed:true})}];
  let tree=app.render(),row=one(tree,'FlashList').renderItem({item:{message:app.props.chat.history.messages[0]}});
  assert.ok(nodes(row).some(node=>node.type==='Text'&&node.props.children===(mode==='content'?'contentRemoved':mode==='empty-media'?'mediaRemoved':'caption survives')),'nonblank tombstone/caption body');
  const press=one(row,'Pressable');assert.equal(one(row,'SwipeReply').enabled,mode!=='content');
  assert.equal(press.accessibilityActions.some(action=>action.name==='reply'),mode!=='content');
  press.onLongPress();tree=app.render();assert.equal(nodes(tree).some(node=>node.type==='MessageQuote'),mode!=='content');
  assert.equal(nodes(row).some(node=>node.type==='MediaTile'),false);
 }
 const app=timeline();let tree=app.render(),item={message:app.props.chat.history.messages[0]},row=one(tree,'FlashList').renderItem({item});
 const swipe=one(row,'SwipeReply'),press=one(row,'Pressable');press.onPress();
 const context=one(one(app.render(),'FlashList').renderItem({item}),'IconButton',props=>props.icon==='reply');
 one(app.render(),'Field').onChangeText('draft remains');
 app.props.chat.history.messages=[{id:10,author_user_id:8,author_name:'Synthetic',created_at:'2026-10-20 10:00:00',text:'',content_removed:true}];app.render();
 swipe.onReply();press.onLongPress();press.onAccessibilityAction({nativeEvent:{actionName:'reply'}});context.onPress();
 tree=app.render();assert.equal(nodes(tree).some(node=>node.type==='MessageQuote'),false);assert.equal(one(tree,'Field').value,'draft remains');
 row=one(tree,'FlashList').renderItem({item:{message:app.props.chat.history.messages[0]}});assert.equal(nodes(row).some(node=>node.type==='IconButton'&&node.props.icon==='reply'),false);
});

test('retention revision clears composer quote and content actions without changing its unsent draft',()=>{
 const app=timeline();let tree=app.render();one(tree,'Field').ref.current={focus(){}};
 const item={key:'message-10',message:app.props.chat.history.messages[0]};one(one(tree,'FlashList').renderItem({item}),'Pressable').onPress();
 one(one(app.render(),'FlashList').renderItem({item}),'IconButton',p=>p.icon==='reply').onPress();
 one(app.render(),'Field').onChangeText('keep unsent draft');assert.equal(one(app.render(),'MessageQuote').text,'retained message');
 app.props.chat.contentEpoch=1;app.props.chat.selected={...app.props.chat.selected,content_revision:1};app.render();tree=app.render();
 assert.equal(nodes(tree).some(n=>n.type==='MessageQuote'),false);assert.equal(one(tree,'Field').value,'keep unsent draft');assert.equal(app.calls.length,0);
});

test('message information and device-local hide undo remain available to read-only members without exposing hidden content', async () => {
  const app = timeline(); app.props.chat.identity.permissions.chat_send = false;
  let list = one(app.render(), 'FlashList'); const item = { key: 'message-10', message: app.props.chat.history.messages[0] };
  one(list.renderItem({ item }), 'Pressable').onPress();
  let row = one(app.render(), 'FlashList').renderItem({ item });
  assert.equal(nodes(row).some(node => node.type === 'IconButton' && node.props.icon === 'reply'), false);
  assert.equal(nodes(row).some(node => node.type === 'IconButton' && node.props.icon === 'trash'), false, 'read-only is not an exception to authorship');
  one(row, 'IconButton', props => props.icon === 'info').onPress(); await settled();
  const sheet = one(app.render(), 'Sheet'); assert.equal(sheet.title, 'messageInfo');
  assert.equal(JSON.stringify(sheet).includes('retained message'), true);
  assert.equal(JSON.stringify(sheet).includes('receiptSummary'), false, 'received message has no invented author-wide receipt status');
  sheet.close();
  item.message.author_user_id = 7; // Own historical messages remain locally hideable after send rights are withdrawn.
  row = one(app.render(), 'FlashList').renderItem({ item }); one(row, 'Pressable').onPress();
  row = one(app.render(), 'FlashList').renderItem({ item });
  one(row, 'IconButton', props => props.icon === 'trash').onPress();
  assert.equal(app.calls.some(call => Array.isArray(call) && call[0] === 'hidden'), false, 'confirmation precedes persistence');
  app.alerts.at(-1)[2].find(action => action.style === 'destructive').onPress(); await settled();
  row = one(app.render(), 'FlashList').renderItem({ item });
  assert.equal(JSON.stringify(row).includes('retained message'), false);
  assert.equal(JSON.stringify(row).includes('MediaTile'), false);
  one(row, 'Button', props => props.title === 'undoHide').onPress(); await settled();
  row = one(app.render(), 'FlashList').renderItem({ item }); assert.equal(JSON.stringify(row).includes('retained message'), true);
});

test('employees and group admins cannot hide received messages or trigger stale hide handlers', async () => {
  const { translator } = load('dictionary.ts', {});
  assert.equal(translator('ar')('hideLocal'), 'إخفاء من جهازي');
  assert.equal(translator('en')('hideLocal'), 'Hide on my device');
  for (const language of ['ar', 'en']) for (const isAdmin of [false, true]) {
    const app = timeline([10]); app.props.language = language; app.props.chat.selected = { ...room, is_group_admin: isAdmin };
    const item = { message: app.props.chat.history.messages[0] };
    let row = one(app.render(), 'FlashList').renderItem({ item });
    assert.equal(JSON.stringify(row).includes('retained message'), true, 'legacy foreign markers must not hide received text');
    assert.equal(one(row, 'Pressable').accessibilityActions.some(action => action.name === 'hide'), false);
    one(row, 'Pressable').onAccessibilityAction({ nativeEvent: { actionName: 'hide' } });
    one(row, 'Pressable').onPress(); row = one(app.render(), 'FlashList').renderItem({ item });
    assert.equal(nodes(row).some(node => node.type === 'IconButton' && node.props.icon === 'trash'), false);
    assert.equal(nodes(row).some(node => node.type === 'IconButton' && node.props.icon === 'reply'), true);
    assert.equal(nodes(row).some(node => node.type === 'IconButton' && node.props.icon === 'info'), true);
    assert.equal(app.alerts.length, 0);
    // A callback captured while the same recycled row was owned cannot hide a received replacement.
    const own = timeline(); const ownItem = { message: own.props.chat.history.messages[0] }; ownItem.message.author_user_id = 7;
    one(one(own.render(), 'FlashList').renderItem({ item: ownItem }), 'Pressable').onPress();
    const trash = one(one(own.render(), 'FlashList').renderItem({ item: ownItem }), 'IconButton', p => p.icon === 'trash');
    trash.onPress(); const confirm = own.alerts.at(-1)[2].find(action => action.style === 'destructive');
    ownItem.message.author_user_id = 8; own.render(); trash.onPress(); confirm.onPress(); await settled();
    assert.equal(own.alerts.length, 1); assert.equal(own.calls.some(call => Array.isArray(call) && call[0] === 'hidden'), false);
  }
  const pendingMetadata = timeline(); pendingMetadata.props.engine.cachedHiddenMessages = () => null;
  pendingMetadata.props.engine.hiddenMessages = () => new Promise(() => {});
  const item = { message: pendingMetadata.props.chat.history.messages[0] };
  let row = one(pendingMetadata.render(), 'FlashList').renderItem({ item });
  assert.equal(JSON.stringify(row).includes('retained message'), true, 'received content never waits for local-hide metadata');
  one(row, 'Pressable').onPress(); row = one(pendingMetadata.render(), 'FlashList').renderItem({ item });
  one(row, 'IconButton', p => p.icon === 'info').onPress(); await settled();
  assert.equal(one(pendingMetadata.render(), 'Sheet').title, 'messageInfo');
});

test('closing message information prevents late fetch resurrection and never dismisses the keyboard', async () => {
  const app = timeline(); let finish;
  app.props.engine.messageInfo = () => new Promise(resolve => { finish = resolve; });
  const item = { key: 'message-10', message: app.props.chat.history.messages[0] };
  one(one(app.render(), 'FlashList').renderItem({ item }), 'Pressable').onPress();
  one(one(app.render(), 'FlashList').renderItem({ item }), 'IconButton', props => props.icon === 'info').onPress();
  one(app.render(), 'Sheet').close(); finish(item.message); await settled();
  assert.equal(nodes(app.render()).some(node => node.type === 'Sheet'), false);
});

test('tapping a reply quote locates and highlights the original without clearing draft or keyboard', async () => {
  const app = timeline(); const original = { ...app.props.chat.history.messages[0], id: 4, text: 'original' };
  app.props.chat.history.messages[0].reply = { id: 4, author_name: 'Synthetic', text: 'original' };
  app.props.chat.jump = async id => { app.calls.push(['jump', id]); app.props.chat.history = { messages: [original], archive: { browsing: true, older: { kind: 'end' }, newer: { kind: 'gap' } } }; };
  one(app.render(), 'Field').onChangeText('keep draft');
  let tree = app.render(), list = one(tree, 'FlashList'); let target;
  list.ref.current = { scrollToIndex: value => { target = value; } };
  const item = { key: 'message-10', message: app.props.chat.history.messages[0] };
  one(list.renderItem({ item }), 'MessageQuote').onPress(); await settled(); app.render(); app.flushFrames();
  assert.deepEqual(app.calls.find(call => Array.isArray(call) && call[0] === 'jump'), ['jump', 4]);
  assert.equal(target.index, 0); assert.equal(target.animated, false); assert.equal(one(app.render(), 'Field').value, 'keep draft');
});

test('own bubbles stay physically right and received left in both languages, including media and queued sends', () => {
  const flat = style => Object.assign({}, ...[style].flat(Infinity).filter(Boolean));
  for (const language of ['ar', 'en']) {
    const app = timeline(); app.props.language = language;
    const tree = app.render(), list = one(tree, 'FlashList');
    assert.equal(flat(tree.props.style).direction, 'ltr', 'physical bubble geometry must not inherit device RTL');
    for (const own of [true, false]) for (const kind of ['text', 'image', 'audio', 'pending']) {
      const item = kind === 'pending' ? { pending: { client_uuid: 'queued-own', text: 'queued text', state: 'queued' } }
        : { message: { ...app.props.chat.history.messages[0], author_user_id: own ? 7 : 8,
          media: kind === 'text' ? undefined : { id: 23, kind } } };
      const mine = own || kind === 'pending';
      const row = list.renderItem({ item });
      assert.equal(row.props.style.alignSelf, mine ? 'flex-end' : 'flex-start', `${language}/${kind}/${mine}`);
      const bubble = one(row, 'View', p => flat(p.style).borderRadius === 18);
      assert.equal(flat(bubble.style).borderBottomLeftRadius, mine ? 18 : 5);
      assert.equal(flat(bubble.style).borderBottomRightRadius, mine ? 5 : 18);
      const text = one(row, 'Text', p => p.selectable === true);
      assert.equal(flat(text.style).writingDirection, language === 'ar' ? 'rtl' : 'ltr', 'text direction remains language-aware');
      assert.equal(nodes(row).some(node => node.type === 'MessageStatus'), mine);
      assert.equal(nodes(row).some(node => node.type === 'View' && flat(node.props.style).alignSelf === 'flex-end'
        && flat(node.props.style).gap === 4), true, 'time/check cluster stays at the physical end');
    }
  }
});

test('swipe reply respects language direction, vertical scrolling, cancellation and revoked send rights', () => {
  const app = timeline();
  const row = one(app.render(), 'FlashList').renderItem({ item: { message: app.props.chat.history.messages[0] } });
  assert.equal(row.type, 'SwipeReply', 'swipe responder must be an ancestor of the Pressable that owns touch start');
  assert.equal(nodes(row).some(node => node.type === 'Pressable'), true);
  assert.equal(row.props.style.maxWidth, '86%', 'row layout belongs to the gesture ancestor, not a full-width intermediary');
  const state = hooks(); let responder, replies = 0;
  const module = load('SwipeReply.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { View: 'View', PanResponder: { create: handlers => { responder = handlers; return { panHandlers: {} }; } } },
    './components': { ...components, Icon: 'Icon' } });
  const props = { enabled: true, language: 'ar', gestureKey: 'scope/message10', onReply: () => replies++, children: element('Text', {}) };
  const render = () => state.render(() => module.SwipeReply(props)); render();
  assert.equal(typeof responder.onMoveShouldSetPanResponderCapture, 'function', 'horizontal swipe must negotiate before the message Pressable keeps the tap');
  assert.equal(responder.onMoveShouldSetPanResponderCapture(null, { dx: -20, dy: 2, numberActiveTouches: 1 }), true);
  assert.equal(responder.onMoveShouldSetPanResponderCapture(null, { dx: -20, dy: 35, numberActiveTouches: 1 }), false, 'capture must yield to vertical history');
  assert.equal(responder.onMoveShouldSetPanResponderCapture(null, { dx: 20, dy: 0, numberActiveTouches: 1 }), false);
  assert.equal(responder.onMoveShouldSetPanResponder(null, { dx: -20, dy: 2, numberActiveTouches: 1 }), true);
  assert.equal(responder.onMoveShouldSetPanResponder(null, { dx: -20, dy: 35, numberActiveTouches: 1 }), false);
  assert.equal(responder.onMoveShouldSetPanResponder(null, { dx: 20, dy: 0, numberActiveTouches: 1 }), false);
  responder.onPanResponderGrant(); responder.onPanResponderRelease(null, { dx: -60, dy: 1 }); assert.equal(replies, 1);
  props.language = 'en'; render(); responder.onPanResponderGrant();
  responder.onPanResponderRelease(null, { dx: 60, dy: 1 }); assert.equal(replies, 2);
  responder.onPanResponderGrant(); responder.onPanResponderMove(null, { dx: 65, dy: 0, numberActiveTouches: 2 });
  responder.onPanResponderRelease(null, { dx: 65, dy: 0 }); assert.equal(replies, 2);
  props.enabled = false; render(); responder.onPanResponderRelease(null, { dx: 65, dy: 0 }); assert.equal(replies, 2);
  props.enabled = true; render(); responder.onPanResponderGrant(); props.gestureKey = 'scope/message11'; render();
  responder.onPanResponderRelease(null, { dx: 65, dy: 0 }); assert.equal(replies, 2, 'recycled rows cannot receive an old gesture');
  responder.onPanResponderGrant(); responder.onPanResponderTerminate();
  responder.onPanResponderRelease(null, { dx: 65, dy: 0 }); assert.equal(replies, 2);
});

test('following threshold is single, receipt/prepend changes do not count as new rows', () => {
  const { TimelineFollow, NEAR_BOTTOM_DP } = load('timelineFollow.ts', {});
  const follow = new TimelineFollow(); assert.equal(NEAR_BOTTOM_DP, 64);
  assert.equal(follow.rows('last'), true); assert.equal(follow.rows('last'), false);
  assert.equal(follow.scroll(1000, 400, 536), true); assert.equal(follow.scroll(1000, 400, 535), false);
  assert.equal(follow.rows('incoming'), false); follow.ownEnqueued(); assert.equal(follow.following, true);
});

test('a later draft or reply selection survives completion of the previous durable send', async () => {
  const app = timeline(); let tree = app.render();
  one(tree, 'Field').onChangeText('first send');
  one(app.render(), app.tools).onSendText();
  one(app.render(), 'Field').onChangeText('new next draft');
  tree = app.render();
  const row = one(tree, 'FlashList').renderItem({ item: { key: 'message-10', message: app.props.chat.history.messages[0] } });
  one(row, 'Pressable').onLongPress(); app.release(); await settled();
  tree = app.render();
  assert.equal(one(tree, 'Field').value, 'new next draft');
  assert.equal(one(tree, 'MessageQuote').text, 'retained message');
});

test('receipt icons preserve server and queue semantics including unknown; no fabricated read state', () => {
  const module = load('MessagePresentation.tsx', { react: {}, 'react/jsx-runtime': jsx,
    'react-native': { View: 'View', Text: 'Text' }, './components': { ...components, Icon: 'Icon' } });
  for (const [state, icon] of [['sent','check'], ['delivered','doubleCheck'], ['read','doubleCheck'], ['queued','clock'], ['sending','clock'], ['unknown','clock'], ['failed','alert'], [undefined,'clock']]) {
    const tree = module.MessageStatus({ state, t });
    assert.equal(one(tree, 'Icon').icon, icon);
    assert.equal(tree.props.accessibilityLabel, state ?? 'unknown');
    assert.equal(one(tree, 'Icon').color, state === 'read' ? colors.blue : state === 'failed' ? colors.danger : colors.muted);
  }
});

test('local durable send unlocks the composer without waiting for network synchronization', async () => {
  const app = timeline(); let finishSync;
  app.props.chat.offline = false;
  app.props.chat.sync = () => new Promise(resolve => { finishSync = resolve; });
  one(app.render(), 'Field').onChangeText('first');
  one(app.render(), app.tools).onSendText(); app.release(); await settled();
  assert.equal(one(app.render(), app.tools).disabled, false, 'network wait must not block typing/sending');
  one(app.render(), 'Field').onChangeText('second');
  one(app.render(), app.tools).onSendText();
  assert.equal(app.calls.filter(call => Array.isArray(call) && call[0] === 'text').length, 2);
  app.release(); finishSync?.(); await settled();
});

test('follow requests coalesce and do not scroll an already aligned timeline repeatedly', () => {
  const app = timeline(); const tree = app.render(); let scrolls = 0;
  const list = one(tree, 'FlashList'); list.ref.current = { scrollToEnd: () => scrolls++ };
  list.onLayout({ nativeEvent: { layout: { height: 400 } } });
  list.onContentSizeChange(320, 1000);
  app.flushFrames();
  assert.equal(scrolls, 1, 'one layout pass, not an unconditional double scroll');
  list.onScroll({ nativeEvent: { contentSize: { height: 1000 }, layoutMeasurement: { height: 400 }, contentOffset: { y: 600 } } });
  app.keyboard.keyboardDidShow(); list.onContentSizeChange(320, 1000); app.flushFrames();
  assert.equal(scrolls, 1, 'identical bottom geometry needs no correction');
});

test('committed list geometry overrides a stale aligned native scroll event when the tail grows', () => {
  const app = timeline(); const tree = app.render(); let scrolls = 0;
  const list = one(tree, 'FlashList'); let height = 1000;
  list.ref.current = { scrollToEnd: () => scrolls++, getChildContainerDimensions: () => ({ height }),
    getWindowSize: () => ({ height: 400 }), getFirstItemOffset: () => 0, getAbsoluteLastScrollOffset: () => 600 };
  list.onScroll({ nativeEvent: { contentSize: { height: 1000 }, layoutMeasurement: { height: 400 }, contentOffset: { y: 600 } } });
  app.flushFrames(); assert.equal(scrolls, 0);
  height = 1080; // FlashList has laid out the new/recycled row; native onScroll is still the old one.
  list.onCommitLayoutEffect(); app.flushFrames();
  assert.equal(scrolls, 1, 'late tail layout must remain visible above the composer');
  list.onScrollBeginDrag();
  list.onScroll({ nativeEvent: { contentSize: { height: 1080 }, layoutMeasurement: { height: 400 }, contentOffset: { y: 100 } } });
  list.onScrollEndDrag(); list.onCommitLayoutEffect(); app.flushFrames();
  assert.equal(scrolls, 1, 'layout settling must not pull a history reader back down');
});
