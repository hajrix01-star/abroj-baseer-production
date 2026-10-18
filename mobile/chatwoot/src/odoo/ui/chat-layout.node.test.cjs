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
  vm.runInNewContext(compiled, { module, exports: module.exports, require: name => dependencies[name] ?? {}, console,
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

function timeline() {
  const state = hooks(); const calls = []; const voiceRights = []; const frames = []; const keyboard = {};
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
    frames,
    'react-native': { Keyboard: { addListener: (name, callback) => { keyboard[name] = callback; return { remove() {} }; } }, AppState: { currentState: 'active' }, KeyboardAvoidingView: 'KeyboardAvoidingView', Platform: { OS: 'android' }, Pressable: 'Pressable', Text: 'Text', View: 'View' },
    '@shopify/flash-list': { FlashList: 'FlashList' }, './components': components, './dictionary': { errorWord: () => 'error' }, './viewModel': viewModel,
    './MediaTools': { AttachmentTools: tools, MediaTile: 'MediaTile', useVoiceSession: (_scope, _report, play, record) => { voiceRights.push([play, record]); return { recording: false }; } },
    './timelineFollow': load('timelineFollow.ts', {}),
    './companyNames': { companyDisplayName: () => 'Synthetic company' },
    './MessagePresentation': { MessageQuote: 'MessageQuote', MessageStatus: 'MessageStatus' },
  });
  return { props, calls, voiceRights, tools, keyboard, frames,
    flushFrames() { for (let i = 0; i < frames.length && i < 100; i++) { const callback = frames[i]; frames[i] = null; callback?.(); } },
    render: () => state.render(() => module.TimelineScreen(props)), release: () => release() };
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
  assert.ok(scrolls > beforeResize + 2);
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
  app.keyboard.keyboardDidShow(); list.onContentSizeChange(); app.flushFrames();
  assert.equal(scrolls, reader);
});

test('reply uses contextual affordance, focuses input and retains quote on failed enqueue; receipt cluster has no permanent reply', async () => {
  const app = timeline(); let tree = app.render(); let focus = 0;
  one(tree, 'Field').ref.current = { focus: () => focus++ };
  let row = one(tree, 'FlashList').renderItem({ item: { key: 'message-10', message: app.props.chat.history.messages[0] } });
  assert.equal(nodes(row).some(n => n.type === 'IconButton' && n.props.icon === 'reply'), false);
  row.props.onPress(); tree = app.render();
  row = one(tree, 'FlashList').renderItem({ item: { key: 'message-10', message: app.props.chat.history.messages[0] } });
  one(row, 'IconButton', p => p.icon === 'reply').onPress(); tree = app.render();
  assert.equal(focus, 1); assert.equal(one(tree, 'MessageQuote').text, 'retained message');
  app.props.engine.enqueue = async () => { throw Error('storage'); };
  one(tree, 'Field').onChangeText('keep draft'); one(app.render(), app.tools).onSendText(); await settled();
  assert.equal(one(app.render(), 'MessageQuote').text, 'retained message');
  assert.equal(one(app.render(), 'Field').value, 'keep draft');
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
  row.props.onLongPress(); app.release(); await settled();
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
