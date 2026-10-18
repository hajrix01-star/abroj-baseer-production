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
const components = { Button: 'Button', Field: 'Field', IconButton: 'IconButton', Label: 'Label', Sheet: 'Sheet', colors,
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

function timeline(initialHidden = []) {
  const state = hooks(); const calls = []; const voiceRights = []; const frames = []; const keyboard = {};
  const alerts = []; let hidden = [...initialHidden];
  let release;
  const tools = function AttachmentTools() {};
  const props = { language: 'ar', t, onMenu: () => calls.push('menu'), back: () => calls.push('back'), manage: () => calls.push('members'),
    engine: { cachedHiddenMessages: () => [...hidden], hiddenMessages: async () => [...hidden],
      setMessageHidden: async (_room, id, value) => { hidden = value ? [...hidden, id] : hidden.filter(item => item !== id); calls.push(['hidden', id, value]); return [...hidden]; },
      messageInfo: async (_room, id) => { calls.push(['info', id]); return props.chat.history.messages.find(message => message.id === id); },
      enqueue: async (_room, text) => { calls.push(['text', text]); await new Promise(resolve => { release = resolve; }); }, enqueueAttachment: async () => undefined, acknowledge: async () => null },
    chat: { selected: room, presentationReady: true, offline: true, busy: false, error: null,
      identity: { user_id: 7, company_ids: [1], permissions: { chat_view: true, chat_send: true, media: true } },
      history: { messages: [{ id: 10, author_user_id: 8, author_name: 'Synthetic', text: 'retained message', created_at: '2026-10-18 12:30:00', media: { id: 1 } }] }, pending: [], capture: () => calls.push('capture'),
    },
  };
  const viewModel = { presentationKey: () => 'scoped', visibleReadIds: () => [], messageTime: () => '15:30', messageDateTime: () => '18/10/2026, 15:30',
    conversationAccess: (identity, selected) => {
      const canSend = !!identity?.company_ids.includes(selected.company_id) && identity.permissions.chat_view === true && identity.permissions.chat_send === true;
      return { directOff: false, canSend, canAttach: canSend && identity.permissions.media === true };
    }, canViewMedia: (identity, selected) => !!identity?.company_ids.includes(selected.company_id) && identity.permissions.chat_view === true && identity.permissions.media === true };
  const module = load('TimelineScreen.tsx', { react: state.react, 'react/jsx-runtime': jsx,
    frames,
    'react-native': { Alert: { alert: (...args) => alerts.push(args) }, Keyboard: { addListener: (name, callback) => { keyboard[name] = callback; return { remove() {} }; } }, AppState: { currentState: 'active' }, KeyboardAvoidingView: 'KeyboardAvoidingView', Platform: { OS: 'android' }, Pressable: 'Pressable', Text: 'Text', View: 'View' },
    '@shopify/flash-list': { FlashList: 'FlashList' }, './components': components, './dictionary': { errorWord: () => 'error' }, './viewModel': viewModel,
    './MediaTools': { AttachmentTools: tools, MediaTile: 'MediaTile', useVoiceSession: (_scope, _report, play, record) => { voiceRights.push([play, record]); return { recording: false }; } },
    './GroupAvatar': { GroupAvatar: 'GroupAvatar' },
    './SwipeReply': { SwipeReply: 'SwipeReply' },
    './timelineFollow': load('timelineFollow.ts', {}),
    './companyNames': { companyDisplayName: () => 'Synthetic company' },
    './MessagePresentation': { MessageQuote: 'MessageQuote', MessageStatus: 'MessageStatus' },
  });
  return { props, calls, voiceRights, tools, keyboard, frames, alerts,
    flushFrames() { for (let i = 0; i < frames.length && i < 100; i++) { const callback = frames[i]; frames[i] = null; callback?.(); } },
    render: () => state.render(() => module.TimelineScreen(props)), release: () => release() };
}
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
