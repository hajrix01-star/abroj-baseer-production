/** Runs the actual useChat hook with React/native/timer seams; not device rendering QA. */
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

function harness() {
  const slots = [];
  let index = 0;
  let appChanged;
  let networkChanged;
  const react = {
    useState(initial) {
      const at = index++;
      if (!(at in slots)) slots[at] = typeof initial === 'function' ? initial() : initial;
      return [
        slots[at],
        value => {
          slots[at] = typeof value === 'function' ? value(slots[at]) : value;
        },
      ];
    },
    useRef(initial) {
      const at = index++;
      return slots[at] ?? (slots[at] = { current: initial });
    },
    useCallback(callback, deps) {
      const at = index++;
      const old = slots[at];
      if (!old || deps.some((value, i) => value !== old.deps[i])) slots[at] = { callback, deps };
      return slots[at].callback;
    },
    useEffect(callback, deps) {
      const at = index++;
      const old = slots[at];
      if (!old || deps.some((value, i) => value !== old.deps[i])) {
        old?.cleanup?.();
        slots[at] = { deps, cleanup: callback() };
      }
    },
  };
  let mode = 'success';
  let expired = false;
  let rejectDeferred;
  let resolveDeferred;
  let roomRows = [{ id: 1, membership_id: 9, company_id: 1, name: 'Before', avatar_version: 1 }];
  let messages = [];
  const tones = [];
  const timers = new Map(); let timerSequence = 0;
  const identity = { user_id: 7, database: 'synthetic', permissions: { chat_view: true } };
  const engine = {
    identity,
    offline: false,
    status: 'ready',
    get leaseRemainingMs() { return expired ? 0 : 86400000; },
    backoffMs: 2000,
    rooms() {
      if (expired) {
        this.status = 'offline_expired';
        throw Object.assign(new Error(), { code: 'offline_expired' });
      }
      return roomRows;
    },
    pending: () => [],
    history: async () => ({ api_version: 2, messages: [...messages], next_before_id: null }),
    restoreOffline: async () => true,
    markDisconnected() {
      this.offline = true;
      this.status = 'offline';
    },
    async refresh() {
      if (mode === 'deferred')
        return new Promise((resolve, reject) => {
          rejectDeferred = reject;
          resolveDeferred = resolve;
        });
      if (mode !== 'success') {
        this.offline = true;
        this.status = 'offline';
        const code =
          mode === 'forbidden'
            ? 'forbidden'
            : mode === 'stale'
              ? 'stale_session'
              : 'connection_failed';
        throw Object.assign(new Error(), {
          code,
          status: mode === 'forbidden' ? 403 : mode === '503' ? 503 : 0,
        });
      }
      this.offline = false;
      this.status = 'ready';
      return this.identity;
    },
  };
  const native = {
    NativeModules: { BWorkFeedback: { play: async kind => { tones.push(kind); return true; }, stop() {} } },
    AppState: {
      currentState: 'active',
      addEventListener(event, callback) {
        appChanged = callback;
        return { remove() {} };
      },
    },
  };
  const modules = {
    react,
    'react-native': native,
    '@react-native-community/netinfo': {
      addEventListener(callback) {
        networkChanged = callback;
        return () => undefined;
      },
    },
    './dictionary': {
      errorWord: error => (error.code === 'offline_expired' ? 'expired' : 'error'),
    },
    '@react-native-async-storage/async-storage': { getItem: async () => null, setItem: async () => undefined },
    '../runtime': { config: { origin: 'https://synthetic.invalid' } },
  };
  const soundModule = { exports: {} };
  const soundCode = ts.transpileModule(readFileSync(join(__dirname, 'messageSounds.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  vm.runInNewContext(soundCode, { module: soundModule, exports: soundModule.exports, require: name => modules[name] ?? {} });
  modules['./messageSounds'] = soundModule.exports;
  const source = readFileSync(join(__dirname, 'useChat.ts'), 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText;
  const mod = { exports: {} };
  vm.runInNewContext(code, {
    module: mod,
    exports: mod.exports,
    require: name => modules[name] ?? {},
    setTimeout: (callback, delay) => { const id = ++timerSequence; timers.set(id, { callback, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    console,
  });
  return {
    engine,
    tones,
    messages(value) { messages = value; },
    metadata(value) { roomRows = [{ ...roomRows[0], ...value }]; },
    render() {
      index = 0;
      return mod.exports.useChat(engine);
    },
    mode(value) {
      mode = value;
    },
    expired() {
      expired = true;
    },
    app(state) {
      native.AppState.currentState = state;
      appChanged(state);
    },
    network(connected = true) {
      networkChanged({ isConnected: connected, isInternetReachable: connected });
    },
    rejectOld() {
      engine.offline = true;
      rejectDeferred(Object.assign(new Error(), { code: 'connection_failed', status: 0 }));
    },
    resolveOld() { engine.offline = false; mode = 'success'; resolveDeferred(engine.identity); },
    leaseTimer() { return [...timers.values()].find(timer => timer.delay === 86400001)?.callback; },
  };
}
async function settled() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}
async function ready() {
  const app = harness();
  app.render();
  await settled();
  assert.equal(app.render().presentationReady, true);
  app.network();
  await settled();
  return app;
}

test('late older navigation cannot replace a newer explicit latest selection or emit a receive tone', async () => {
  const app = await ready(); let release;
  app.engine.latest = async () => ({ api_version: 2, messages: [{ id: 900, author_user_id: 9 }], next_before_id: 900 });
  await app.render().select(app.engine.rooms()[0]);
  app.engine.history = async (_room, before) => before ? new Promise(resolve => { release = resolve; }) : app.engine.latest();
  const older = app.render().older(); await settled();
  await app.render().latest();
  release({ api_version: 2, messages: [{ id: 1, author_user_id: 9 }], next_before_id: null }); await older;
  assert.equal(app.render().history.messages[0].id, 900);
  assert.equal(app.tones.length, 0);
});

test('foreground permits valid offline cache when internet is up but Odoo/VPN is unavailable', async () => {
  for (const failure of ['network', '503']) {
    const app = await ready();
    app.app('background');
    assert.equal(app.render().presentationReady, false);
    app.mode(failure);
    app.app('active');
    await settled();
    assert.equal(app.engine.offline, true);
    assert.equal(app.render().presentationReady, true);
  }
});
test('same-account resume and reconnect retain TTL-valid display but never grant foreground authority before verification', async () => {
  for (const transition of ['resume', 'reconnect']) {
    const app = await ready();
    const before = app.render(); assert.equal(before.displayReady, true);
    app.mode('deferred');
    if (transition === 'resume') {
      app.app('background');
      const hidden = app.render();
      assert.equal(hidden.foreground, false); assert.equal(hidden.displayReady, false);
      assert.equal(hidden.retainedDisplay, true, 'private tree survives behind background cover');
      app.app('active');
    } else { app.network(false); app.render(); app.network(true); }
    await settled();
    const pending = app.render();
    assert.equal(pending.presentationReady, false, transition);
    assert.equal(pending.displayReady, true, transition);
    assert.equal(pending.retainedDisplay, true, transition);
    assert.equal(pending.identity.user_id, before.identity.user_id);
    app.resolveOld(); await settled();
    assert.equal(app.render().presentationReady, true, transition);
    assert.equal(app.tones.length, 0, 'catchup never emits a tone');
  }
});
test('retained foreground pixels reject expired leases, account scope changes and denied revalidation', async () => {
  for (const transition of ['expired', 'scope', 'actor', 'forbidden', 'stale']) {
    const app = await ready(); app.app('background'); app.render();
    app.mode(['forbidden', 'stale'].includes(transition) ? transition : 'deferred');
    if (transition === 'expired') app.expired();
    if (transition === 'scope') app.engine.accountScope = 'different-login-epoch';
    if (transition === 'actor') app.engine.identity = { ...app.engine.identity, user_id: 8 };
    app.app('active'); await settled();
    assert.equal(app.render().displayReady, false, transition);
    assert.equal(app.render().presentationReady, false, transition);
  }
});
test('one local retained-display deadline masks a hung renewal and old deadline callbacks cannot mask a newer verified scope', async () => {
  for (const becameOnline of [false, true]) {
    const app = await ready(); app.mode('deferred'); app.app('background'); app.render(); app.app('active');
    await settled(); app.render();
    const deadline = app.leaseTimer(); assert.equal(typeof deadline, 'function');
    if (becameOnline) {
      // Refresh can complete before a selected history read; retained display
      // must still expire even when rooms() is no longer in offline mode.
      const rows = app.engine.rooms(); app.engine.rooms = () => rows; app.engine.offline = false;
    }
    app.expired(); deadline();
    assert.equal(app.render().displayReady, false);
    assert.equal(app.render().presentationReady, false);
    app.render().capture(); assert.equal(app.render().displayReady, false, 'a later capture cannot resurrect expired pixels');
  }
  const app = await ready(); app.mode('deferred'); app.app('background'); app.render(); app.app('active');
  await settled(); app.render(); const oldDeadline = app.leaseTimer();
  app.resolveOld(); await settled(); app.render();
  app.engine.accountScope = 'new-verified-scope'; await app.render().sync(); app.render();
  app.expired(); oldDeadline();
  assert.equal(app.render().presentationReady, true);
  assert.equal(app.render().displayReady, true, 'cleaned old deadline cannot affect a newer verified authority');
  const missing = await ready(); delete missing.engine.leaseRemainingMs;
  missing.mode('deferred'); missing.app('background'); missing.render(); missing.app('active'); await settled();
  assert.equal(missing.render().displayReady, false, 'an unavailable deadline never grants unlimited retained display');
});
test('403, missing identity, expired cache and stale-session errors never unlock foreground cache', async () => {
  for (const failure of ['forbidden', 'expired', 'identity_missing', 'stale']) {
    const app = await ready();
    app.app('background');
    app.mode(failure === 'expired' || failure === 'identity_missing' ? 'network' : failure);
    if (failure === 'expired') app.expired();
    if (failure === 'identity_missing') app.engine.identity = null;
    app.app('active');
    await settled();
    assert.equal(app.render().presentationReady, false, failure);
  }
});
test('an earlier foreground request cannot unlock a later foreground epoch', async () => {
  const app = await ready();
  app.mode('deferred');
  app.app('background');
  app.app('active');
  await settled();
  app.app('background');
  app.app('active');
  app.rejectOld();
  await settled();
  assert.equal(app.render().presentationReady, false);
});
test('selected room receives only new remote batches, not selection, receipt/self history or foreground catchup', async () => {
  const app = await ready(); const msg = (id, author_user_id = 9) => ({ id, author_user_id });
  app.messages([msg(1)]); await app.render().select(app.engine.rooms()[0]); app.render();
  assert.equal(app.tones.length, 0);
  app.messages([msg(1), msg(2), msg(3)]); await app.render().sync(); app.render();
  assert.deepEqual(app.tones, ['receive']);
  await app.render().sync(); app.messages([msg(1), msg(2), msg(3), msg(4, 7)]); await app.render().sync();
  assert.equal(app.tones.length, 1);
  app.app('background'); app.messages([msg(5), msg(6)]); app.app('active'); await settled(); app.render();
  assert.equal(app.tones.length, 1);
  app.messages([msg(5), msg(6), msg(7)]); await app.render().sync(); assert.equal(app.tones.length, 2);
});
test('same membership metadata refresh replaces selected name/avatar without clearing history or reselection', async () => {
  const app = await ready(); app.messages([{ id: 1, author_user_id: 9 }]);
  await app.render().select(app.engine.rooms()[0]); const before = app.render().history;
  app.metadata({ name: 'After', avatar_version: 2 }); app.render().capture();
  const current = app.render();
  assert.equal(current.selected.name, 'After'); assert.equal(current.selected.avatar_version, 2);
  assert.equal(current.history, before); assert.equal(app.tones.length, 0);
});
test('a history response started before reconnect cannot emit a catchup receive tone', async () => {
  const app = await ready(); const msg = id => ({ id, author_user_id: 9 });
  app.messages([msg(1)]); await app.render().select(app.engine.rooms()[0]); app.render();
  let release; app.engine.history = () => new Promise(resolve => { release = resolve; });
  const old = app.render().sync(); await settled();
  app.network(false); app.network(true); app.engine.offline = false;
  release({ api_version: 2, messages: [msg(1), msg(2)], next_before_id: null }); await old;
  assert.equal(app.tones.length, 0);
});
test('late selected initial history cannot reset a newer reconnect baseline and replay catchup audio', async () => {
  const app = await ready(); const msg = id => ({ id, author_user_id: 9 });
  let release; let reads = 0;
  app.engine.history = () => ++reads === 1
    ? new Promise(resolve => { release = resolve; })
    : Promise.resolve({ api_version: 2, messages: [msg(1), msg(2)], next_before_id: null });
  const selected = app.render().select(app.engine.rooms()[0]);
  app.network(false); app.network(true); await settled(); app.render();
  assert.equal(app.tones.length, 0);
  release({ api_version: 2, messages: [msg(1)], next_before_id: null }); await selected; app.render();
  await app.render().sync();
  assert.equal(app.tones.length, 0, 'already caught-up message2 must remain silent after late initial selection');
});
