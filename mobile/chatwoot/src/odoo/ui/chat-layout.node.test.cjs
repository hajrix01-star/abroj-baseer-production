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
      useCallback(value) { index++; return value; },
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
const components = { Button: 'Button', Field: 'Field', IconButton: 'IconButton', Label: 'Label', colors,
  styles: { fill: { flex: 1 }, row: {}, card: {}, header: {}, text: {}, muted: {}, title: {} }, direction: () => ({}) };
function load(file, dependencies) {
  const compiled = ts.transpileModule(readFileSync(join(__dirname, file), 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => dependencies[name] ?? {}, console }, { filename: file });
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

function timeline() {
  const state = hooks(); const calls = []; const voiceRights = [];
  let release;
  const tools = function AttachmentTools() {};
  const props = { language: 'ar', t, onMenu: () => calls.push('menu'), back: () => calls.push('back'), manage: () => calls.push('members'),
    engine: { enqueue: async (_room, text) => { calls.push(['text', text]); await new Promise(resolve => { release = resolve; }); }, enqueueAttachment: async () => undefined, acknowledge: async () => null },
    chat: { selected: room, presentationReady: true, offline: true, busy: false, error: null,
      identity: { user_id: 7, company_ids: [1], permissions: { chat_view: true, chat_send: true, media: true } },
      history: { messages: [{ id: 10, author_user_id: 8, author_name: 'Synthetic', text: 'retained message', created_at: '2026-10-18 12:30:00', media: { id: 1 } }] }, pending: [], capture: () => calls.push('capture'),
    },
  };
  const viewModel = { presentationKey: () => 'scoped', visibleReadIds: () => [], messageTime: () => '15:30',
    conversationAccess: (identity, selected) => {
      const canSend = !!identity?.company_ids.includes(selected.company_id) && identity.permissions.chat_view === true && identity.permissions.chat_send === true;
      return { directOff: false, canSend, canAttach: canSend && identity.permissions.media === true };
    }, canViewMedia: (identity, selected) => !!identity?.company_ids.includes(selected.company_id) && identity.permissions.chat_view === true && identity.permissions.media === true };
  const module = load('TimelineScreen.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    'react-native': { AppState: { currentState: 'active' }, KeyboardAvoidingView: 'KeyboardAvoidingView', Platform: { OS: 'android' }, Pressable: 'Pressable', Text: 'Text', View: 'View' },
    '@shopify/flash-list': { FlashList: 'FlashList' }, './components': components, './dictionary': { errorWord: () => 'error' }, './viewModel': viewModel,
    './MediaTools': { AttachmentTools: tools, MediaTile: 'MediaTile', useVoiceSession: (_scope, _report, play, record) => { voiceRights.push([play, record]); return { recording: false }; } },
  });
  return { props, calls, voiceRights, tools, render: () => state.render(() => module.TimelineScreen(props)), release: () => release() };
}

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

test('timeline gives history the remaining height, caps inline input and dispatches a draft only once before durable enqueue', async () => {
  const app = timeline();
  let tree = app.render();
  assert.equal(one(tree, 'KeyboardAvoidingView').style[1].minHeight, 0);
  const list = one(tree, 'FlashList');
  assert.equal(nodes(tree).find(node => node.type === 'View' && node.props.children?.type === 'FlashList').props.style.flex, 1);
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
