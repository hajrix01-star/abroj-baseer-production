/** Same production SQL on real SQLite, not an array/map simulation of a database. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { mkdtempSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { performance } from 'node:perf_hooks';
import { SqliteArchiveStore } from '../storage/SqliteHistoryArchive.ts';
import type { ArchiveDatabase } from '../storage/SqliteHistoryArchive.ts';
import type { History, Message } from '../core/ChatEngine.ts';
import type { HistoryScope } from '../core/HistoryArchive.ts';
import { ChatEngine, ChatError } from '../core/ChatEngine.ts';
import type { Request, Room, Storage } from '../core/ChatEngine.ts';

const scope: HistoryScope = {
  account: 'https://private.example/trial/u/7/',
  companyId: 1,
  roomId: 11,
  membershipId: 21,
};
const guard = () => {};
const message = (id: number, mediaId?: number): Message => ({
  id,
  author_user_id: 7,
  author_name: 'Synthetic user',
  text: `synthetic archive ${id}`,
  created_at: '2026-10-18T12:00:00Z',
  ...(mediaId
    ? {
        media: {
          id: mediaId,
          mime: 'image/jpeg',
          kind: 'image',
          size: 4096,
          sha256: 'a'.repeat(64),
          thumbnail_available: true,
        },
      }
    : {}),
});
function harness(path = ':memory:', limits?: { accountMessages: number; accountBytes: number }) {
  const db = new DatabaseSync(path);
  let afterQuery: ((sql: string) => void) | undefined;
  const operations: { sql: string; returned: number }[] = [];
  const record = <T>(sql: string, result: T): T => {
    operations.push({ sql, returned: Array.isArray(result) ? result.length : result ? 1 : 0 });
    afterQuery?.(sql);
    return result;
  };
  const driver: ArchiveDatabase = {
    async execAsync(sql) {
      db.exec(sql);
      record(sql, undefined);
    },
    async runAsync(sql, ...params) {
      return record(sql, db.prepare(sql).run(...params));
    },
    async getFirstAsync<T>(sql: string, ...params: (string | number | null)[]) {
      return record(sql, (db.prepare(sql).get(...params) as T) ?? null);
    },
    async getAllAsync<T>(sql: string, ...params: (string | number | null)[]) {
      return record(sql, db.prepare(sql).all(...params) as T[]);
    },
  };
  return {
    store: new SqliteArchiveStore(async () => driver, limits),
    db,
    operations,
    hook: (fn?: (sql: string) => void) => {
      afterQuery = fn;
    },
  };
}
const latest = { direction: 'latest' as const, limit: 60, maxBytes: 256 * 1024 };
const history = (ids: number[], terminal = false): History => ({
  api_version: 2,
  messages: ids.map(id => message(id, id === 6 ? 70 : undefined)),
  next_before_id: terminal ? null : (ids[0] ?? null),
});

test('SQLite pages traverse >500 sparse IDs, bounded keyset queries and indexed old media', async () => {
  const { store, db, operations } = harness();
  const all = Array.from({ length: 660 }, (_, index) => (index + 1) * 3);
  let before: number | null = null;
  for (let end = all.length; end > 0; end -= 30) {
    const ids = all.slice(Math.max(0, end - 30), end);
    await store.commitPage(scope, { beforeId: before, history: history(ids, end <= 30) }, guard);
    before = ids[0]!;
  }
  const ids: number[] = [];
  let slice = await store.read(scope, latest, guard);
  ids.unshift(...slice.messages.map(row => row.id));
  while (slice.older.kind === 'cached') {
    slice = await store.read(
      scope,
      { ...latest, direction: 'before', anchorId: slice.messages[0]!.id },
      guard,
    );
    ids.unshift(...slice.messages.map(row => row.id));
  }
  assert.deepEqual(ids, all);
  assert.equal(slice.older.kind, 'end');
  assert.equal((await store.findMedia(scope, 70, guard))?.id, 6);
  assert.equal(await store.findMedia({ ...scope, membershipId: 22 }, 70, guard), null);
  assert.ok(
    operations
      .filter(op => /SELECT message_id,json,bytes/.test(op.sql))
      .every(op => op.returned <= 61),
  );
  const plan = db
    .prepare(
      'EXPLAIN QUERY PLAN SELECT message_id,json,bytes FROM archive_messages WHERE account=? AND scope=? AND message_id<? ORDER BY message_id DESC LIMIT 60',
    )
    .all(scope.account, JSON.stringify([scope.account, 1, 11, 21]), 900);
  assert.match(JSON.stringify(plan), /SEARCH archive_messages USING PRIMARY KEY/);
  assert.doesNotMatch(operations.map(op => op.sql).join('\n'), /\bOFFSET\b/i);
  db.close();
});

test('disconnected heads do not certify skipped messages; filling bridge joins coverage', async () => {
  const { store, db } = harness();
  await store.commitPage(scope, { beforeId: null, history: history([1, 2, 3], true) }, guard);
  await store.commitPage(scope, { beforeId: null, history: history([101, 102, 103]) }, guard);
  const head = await store.read(scope, latest, guard);
  assert.deepEqual(
    head.messages.map(row => row.id),
    [101, 102, 103],
  );
  assert.equal(head.older.kind, 'gap');
  assert.equal(head.partial, true);
  await store.commitPage(scope, { beforeId: 101, history: history([2, 3, 4], false) }, guard);
  const filled = await store.read(scope, latest, guard);
  assert.deepEqual(
    filled.messages.map(row => row.id),
    [1, 2, 3, 4, 101, 102, 103],
  );
  assert.equal(filled.older.kind, 'end');
  db.close();
});

test('legacy import never certifies internal gaps; authoritative page supersedes only proven interval', async () => {
  const { store, db } = harness();
  await store.importLegacy(scope, history([], true), guard);
  const empty = await store.read(scope, latest, guard);
  assert.equal(empty.latestId, null);
  assert.notEqual(empty.older.cursor, 0);
  assert.notEqual(empty.newer.cursor, 0);
  const legacy = history([1, 2, 3, 100, 101, 102], true);
  await store.importLegacy(scope, legacy, guard);
  await store.importLegacy(scope, legacy, guard);
  assert.equal(db.prepare('SELECT COUNT(*) AS count FROM archive_coverage').get()?.count, 0);
  let read = await store.read(scope, latest, guard);
  assert.equal(read.partial, true);
  assert.equal(read.unverified, true);
  assert.notEqual(read.older.kind, 'end');
  assert.notEqual(read.newer.kind, 'end');
  await store.commitPage(scope, { beforeId: null, history: history([100, 101, 102]) }, guard);
  read = await store.read(scope, latest, guard);
  assert.deepEqual(
    read.messages.map(row => row.id),
    [100, 101, 102],
  );
  assert.equal(read.older.kind, 'gap');
  assert.equal(read.unverified, false);
  await store.commitPage(scope, { beforeId: 100, history: history([1, 2, 3], true) }, guard);
  read = await store.read(scope, latest, guard);
  assert.equal(read.partial, false);
  assert.equal(read.older.kind, 'end');
  db.close();
});

test('before-exclusive boundary uses newly proven preceding interval rather than unknown legacy interior', async () => {
  const { store, db } = harness();
  await store.importLegacy(scope, history([1, 2, 3, 50, 51, 52, 100, 101, 102], true), guard);
  await store.commitPage(scope, { beforeId: 100, history: history([50, 51, 52]) }, guard);
  const cached = await store.read(scope, { ...latest, direction: 'before', anchorId: 100 }, guard);
  assert.deepEqual(
    cached.messages.map(row => row.id),
    [50, 51, 52],
  );
  assert.equal(cached.unverified, false);
  assert.equal(cached.partial, true);
  assert.equal(cached.older.kind, 'gap');
  db.close();
});

test('late invalidation rolls back SQL; ordered purge cannot resurrect or remove new same-account rows', async () => {
  const { store, db, hook } = harness();
  let epoch = 1;
  const scopedGuard = (expected: number) => () => {
    if (epoch !== expected) throw new Error('stale_session');
  };
  await store.commitPage(scope, { beforeId: null, history: history([1, 2], true) }, scopedGuard(1));
  hook(sql => {
    if (sql.startsWith('INSERT INTO archive_messages')) {
      epoch = 2;
      hook();
    }
  });
  await assert.rejects(
    store.commitPage(scope, { beforeId: null, history: history([3, 4]) }, scopedGuard(1)),
    /stale_session/,
  );
  assert.deepEqual(
    (await store.read(scope, latest, scopedGuard(2))).messages.map(row => row.id),
    [1, 2],
  );
  await store.purgeAccount(scope.account, scopedGuard(2));
  await store.commitPage(scope, { beforeId: null, history: history([5], true) }, scopedGuard(2));
  await assert.rejects(store.purgeAccount(scope.account, scopedGuard(1)), /stale_session/);
  assert.equal((await store.read(scope, latest, scopedGuard(2))).messages[0]?.id, 5);
  db.close();
});

test('scope reconciliation and media-right removal redact old records across company/member boundaries', async () => {
  const { store, db } = harness();
  const other = { ...scope, companyId: 2, roomId: 12, membershipId: 30 };
  await store.commitPage(scope, { beforeId: null, history: history([3, 6], true) }, guard);
  await store.commitPage(other, { beforeId: null, history: history([6], true) }, guard);
  await store.reconcile(scope.account, [scope], false, guard);
  assert.equal(await store.findMedia(scope, 70, guard), null);
  assert.equal(
    (await store.read(scope, latest, guard)).messages.find(row => row.id === 6)?.media,
    undefined,
  );
  assert.equal((await store.read(other, latest, guard)).messages.length, 0);
  await store.purgeAccount(scope.account, guard);
  assert.equal(db.prepare('SELECT COUNT(*) AS count FROM archive_messages').get()?.count, 0);
  db.close();
});

test('account row/byte quotas atomically evict whole scopes or reset active cache without false end', async () => {
  const { store, db } = harness(':memory:', { accountMessages: 4, accountBytes: 4096 });
  const other = { ...scope, roomId: 12 };
  await store.commitPage(scope, { beforeId: null, history: history([1, 2, 3], true) }, guard);
  await store.commitPage(other, { beforeId: null, history: history([4, 5, 6]) }, guard);
  assert.equal((await store.read(scope, latest, guard)).messages.length, 0);
  await store.commitPage(other, { beforeId: 4, history: history([1, 2, 3]) }, guard);
  const active = await store.read(other, latest, guard);
  assert.equal(active.messages.length, 0);
  assert.equal(active.partial, true);
  assert.notEqual(active.older.kind, 'end');
  assert.equal(active.latestId, 6);
  assert.equal(active.older.kind, 'fetch');
  const older = await store.read(other, { ...latest, direction: 'before', anchorId: 3 }, guard);
  assert.deepEqual(
    older.messages.map(row => row.id),
    [1, 2],
  );
  assert.ok(
    Number(db.prepare('SELECT SUM(row_count) AS count FROM archive_scopes').get()?.count) <= 4,
  );
  db.close();
});

test('empty terminal snapshots remove stale rows and recover, with bounded JSON reads', async () => {
  const { store, db } = harness();
  await store.commitPage(scope, { beforeId: null, history: history([1, 2, 3], true) }, guard);
  await store.commitPage(scope, { beforeId: 3, history: history([], true) }, guard);
  assert.deepEqual(
    (await store.read(scope, latest, guard)).messages.map(row => row.id),
    [3],
  );
  await store.commitPage(scope, { beforeId: null, history: history([], true) }, guard);
  const empty = await store.read(scope, latest, guard);
  assert.equal(empty.messages.length, 0);
  assert.equal(empty.older.kind, 'end');
  await store.commitPage(scope, { beforeId: null, history: history([7], true) }, guard);
  assert.equal((await store.read(scope, latest, guard)).messages[0]?.id, 7);
  await store.commitPage(scope, { beforeId: null, history: history([7, 8, 9], true) }, guard);
  const maxBytes = Buffer.byteLength(JSON.stringify([message(8), message(9)])) - 1;
  const limited = await store.read(scope, { ...latest, maxBytes }, guard);
  assert.ok(Buffer.byteLength(JSON.stringify(limited.messages)) <= maxBytes);
  assert.equal(limited.messages.length, 1);
  db.close();
});

test('private SQLite survives reopening, media catalog actor isolation and parameter binding', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'bwork-archive-test-'));
  const path = join(directory, 'archive.db');
  const actor = 'a'.repeat(64);
  const entry = {
    uri: 'file:///private/c1-r11-m21/media-7-preview.jpg',
    bytes: 64,
    sha256: 'b'.repeat(64),
    usedAt: 1,
  };
  let current = harness(path);
  try {
    const quoted = { ...scope, account: "private' OR 1=1--" };
    await current.store.commitPage(quoted, { beforeId: null, history: history([6], true) }, guard);
    await current.store.mediaCacheCatalog.put(actor, entry);
    current.db.close();
    current = harness(path);
    assert.equal((await current.store.read(quoted, latest, guard)).messages.length, 1);
    assert.equal((await current.store.read(scope, latest, guard)).messages.length, 0);
    assert.deepEqual(
      (await current.store.mediaCacheCatalog.list(actor)).map(row => ({ ...row })),
      [entry],
    );
    assert.deepEqual(await current.store.mediaCacheCatalog.list('c'.repeat(64)), []);
    await current.store.mediaCacheCatalog.touch(actor, entry.uri, 2);
    assert.equal((await current.store.mediaCacheCatalog.list(actor))[0]?.usedAt, 2);
    await current.store.mediaCacheCatalog.remove(actor, entry.uri);
    assert.deepEqual(await current.store.mediaCacheCatalog.list(actor), []);
    await assert.rejects(current.store.mediaCacheCatalog.put('../x', entry), {
      code: 'invalid_media_cache',
    });
  } finally {
    current.db.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test('cache offline pins policy and clock highwater survive real SQLite restart without changing normal catalog upserts',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'bwork-cache-policy-')),path=join(directory,'cache.db'),actor='a'.repeat(64),other='c'.repeat(64);
  const entry={uri:'file:///private/c1-r11-m21/media-7.jpg',bytes:64,sha256:'b'.repeat(64),usedAt:100};let current=harness(path);
  try{
    assert.deepEqual(await current.store.mediaCacheCatalog.policy(actor),{autoClean30Days:false,highWater:0});
    await current.store.mediaCacheCatalog.put(actor,entry);await current.store.mediaCacheCatalog.keep(actor,entry.uri,entry.sha256,true);
    await current.store.mediaCacheCatalog.setPolicy(actor,true);assert.equal(await current.store.mediaCacheCatalog.clock(actor,200),true);assert.equal(await current.store.mediaCacheCatalog.clock(actor,199),false);
    await current.store.mediaCacheCatalog.put(actor,{...entry,usedAt:150});current.db.close();current=harness(path);
    assert.deepEqual(await current.store.mediaCacheCatalog.pins(actor),[{uri:entry.uri,sha256:entry.sha256}]);assert.deepEqual(await current.store.mediaCacheCatalog.pins(other),[]);
    assert.deepEqual(await current.store.mediaCacheCatalog.policy(actor),{autoClean30Days:true,highWater:200});assert.equal(await current.store.mediaCacheCatalog.clock(actor,199),false);
    await current.store.mediaCacheCatalog.remove(actor,entry.uri);assert.equal((await current.store.mediaCacheCatalog.pins(actor)).length,1,'intent is not fabricated availability');
    await current.store.mediaCacheCatalog.clearPins(actor);assert.deepEqual(await current.store.mediaCacheCatalog.pins(actor),[]);
  }finally{current.db.close();rmSync(directory,{recursive:true,force:true});}
});

test('retained gallery media survives SQLite restart without claiming history coverage and is redacted by scope or media revocation',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'bwork-retained-media-')),path=join(directory,'cache.db');let current=harness(path);
  const item=message(777,70);item.media!.name='retained.jpg';
  try{
    await current.store.retainMediaAssociation(scope,item,70,guard);
    for(const table of ['archive_scopes','archive_messages','archive_coverage'])assert.equal((current.db.prepare(`SELECT COUNT(*) AS count FROM ${table}`).get() as any).count,0);
    current.db.close();current=harness(path);assert.equal((await current.store.findMedia(scope,70,guard))?.id,777);
    assert.equal(await current.store.findMedia({...scope,membershipId:22},70,guard),null);
    await current.store.reconcile(scope.account,[scope],false,guard);assert.equal(await current.store.findMedia(scope,70,guard),null);
    await current.store.retainMediaAssociation(scope,item,70,guard);await current.store.reconcile(scope.account,[],true,guard);assert.equal(await current.store.findMedia(scope,70,guard),null);
    await current.store.retainMediaAssociation(scope,item,70,guard);await current.store.purgeAccount(scope.account,guard);assert.equal(await current.store.findMedia(scope,70,guard),null);
    await assert.rejects(current.store.retainMediaAssociation(scope,item,71,guard),{code:'invalid_archive_row'});
  }finally{current.db.close();rmSync(directory,{recursive:true,force:true});}
});
test('retention metadata clear is room scoped and durable on real SQLite restart without deleting file catalog pins or policy',async()=>{
 const directory=mkdtempSync(join(tmpdir(),'bwork-retention-clear-')),path=join(directory,'history.db'),actor='c'.repeat(64),uri='file:///private/media-70.jpg';let current=harness(path);
 try{
  const item=message(1,70);item.media!.name='retained.jpg';await current.store.commitPage(scope,{beforeId:null,history:{api_version:2,messages:[item],next_before_id:null}},guard);
  await current.store.retainMediaAssociation(scope,item,70,guard);const other={...scope,roomId:12,membershipId:22};await current.store.commitPage(other,{beforeId:null,history:{api_version:2,messages:[message(2)],next_before_id:null}},guard);
  await current.store.mediaCacheCatalog.put(actor,{uri,bytes:4096,sha256:'a'.repeat(64),usedAt:1});await current.store.mediaCacheCatalog.keep(actor,uri,'a'.repeat(64),true);await current.store.mediaCacheCatalog.setPolicy(actor,true);
  await current.store.clearRoom(scope,guard);current.db.close();current=harness(path);
  assert.equal(await current.store.findMedia(scope,70,guard),null);assert.equal((await current.store.read(scope,{direction:'latest',limit:30,maxBytes:262144},guard)).messages.length,0);
  assert.equal((await current.store.read(other,{direction:'latest',limit:30,maxBytes:262144},guard)).messages[0]?.id,2);
  assert.ok(await current.store.mediaCacheCatalog.pin(actor,uri));assert.ok(await current.store.mediaCacheCatalog.get(actor,uri));assert.equal((await current.store.mediaCacheCatalog.policy(actor)).autoClean30Days,true);
 }finally{current.db.close();rmSync(directory,{recursive:true,force:true});}
});

test('retained media bounds use real SQLite account rows and bytes and reject stale guarded transactions',async()=>{
  const current=harness(),item=message(1,1);item.media!.name='retained.jpg';
  try{
    await current.store.retainMediaAssociation(scope,item,1,guard);
    const scoped=JSON.stringify([scope.account,scope.companyId,scope.roomId,scope.membershipId]),json=JSON.stringify(item);
    current.db.prepare('DELETE FROM retained_media').run();
    current.db.prepare(`WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<5000) INSERT INTO retained_media(account,scope,media_id,message_id,json,bytes) SELECT ?,?,x,x,json_set(?,'$.id',x,'$.media.id',x),length(CAST(json_set(?,'$.id',x,'$.media.id',x) AS BLOB)) FROM n`).run(scope.account,scoped,json,json);
    const over=message(5001,5001);over.media!.name='retained.jpg';await assert.rejects(current.store.retainMediaAssociation(scope,over,5001,guard),{code:'media_quota'});
    assert.equal((await current.store.findMedia(scope,5000,guard))?.id,5000);
    current.db.prepare('DELETE FROM retained_media').run();let inserted=0;
    for(let n=1;n<=70;n++){const big=message(n,n);big.media!.name='retained.jpg';big.text='x'.repeat(120000);try{await current.store.retainMediaAssociation(scope,big,n,guard);inserted++;}catch(error){assert.equal((error as any).code,'media_quota');break;}}
    assert.ok(inserted>0&&inserted<70);assert.ok(Number((current.db.prepare('SELECT SUM(bytes) AS bytes FROM retained_media').get() as any).bytes)<=8*1024*1024);
    current.db.prepare('DELETE FROM retained_media').run();
    const metadataScope={...scope,account:'synthetic-account-'.repeat(250)},large=message(1,1);large.media!.name='retained.jpg';large.text='x'.repeat(523000);
    assert.ok(Buffer.byteLength(JSON.stringify(large))*16<8*1024*1024,'sixteen JSON payloads alone fit; metadata must consume the remaining budget');
    for(let n=1;n<=15;n++)await current.store.retainMediaAssociation(metadataScope,{...large,id:n,media:{...large.media!,id:n}},n,guard);
    await assert.rejects(current.store.retainMediaAssociation(metadataScope,{...large,id:16,media:{...large.media!,id:16}},16,guard),{code:'media_quota'});
    const declared=current.db.prepare('SELECT bytes,json,account,scope,media_id,message_id FROM retained_media LIMIT 1').get() as any;
    assert.equal(declared.bytes,Buffer.byteLength(JSON.stringify({account:declared.account,scope:declared.scope,media_id:declared.media_id,message_id:declared.message_id,message:JSON.parse(declared.json)})));
    await assert.rejects(current.store.retainMediaAssociation(scope,item,1,()=>{throw new Error('stale');}),/stale/);
  }finally{current.db.close();}
});

test('real ChatEngine/SQLite integration: deep paging, local page reuse, stable browsing, offline restart and durable send', async () => {
  const { store, db } = harness();
  const data = new Map<string, string>();
  const storage: Storage = {
    async getItem(key) {
      return data.get(key) ?? null;
    },
    async setItem(key, value) {
      data.set(key, value);
    },
    async removeItem(key) {
      data.delete(key);
    },
    async getAllKeys() {
      return [...data.keys()];
    },
  };
  const room: Room = {
    id: 11,
    company_id: 1,
    membership_id: 21,
    name: 'Synthetic integration',
    is_group: true,
  };
  let offline = false,
    gets = 0;
  const source = Array.from({ length: 720 }, (_, index) =>
    message((index + 1) * 3, index === 1 ? 70 : undefined),
  );
  const transport = {
    async request(request: Request): Promise<unknown> {
      if (offline) throw new ChatError('connection_failed');
      if (request.path === '/web/session/destroy') return { result: null };
      if (request.path === '/web/session/authenticate') return { result: { uid: 7, db: 'trial' } };
      if (request.path === '/bwork/api/v2/bootstrap')
        return {
          api_version: 2,
          user_id: 7,
          database: 'trial',
          company_ids: [1],
          csrf_token: 'synthetic',
          permissions: { chat_view: true, chat_send: true, media: true, revision: 1 },
        };
      if (request.path === '/bwork/api/v2/rooms') return { api_version: 2, rooms: [room] };
      if (request.path.startsWith('/bwork/api/v2/changes'))
        return { api_version: 2, changes: [], next_after: 0, watermark: 0, reset_required: false };
      if (request.path.includes('/messages') && request.method === 'GET') {
        gets++;
        const before =
          Number(
            new URL(`https://synthetic.invalid${request.path}`).searchParams.get('before_id'),
          ) || Infinity;
        const eligible = source.filter(row => row.id < before),
          page = eligible.slice(-30);
        return {
          api_version: 2,
          messages: page,
          next_before_id: eligible.length > 30 ? page[0]!.id : null,
        };
      }
      throw new Error(`unexpected synthetic route ${request.path}`);
    },
  };
  const options = {
    storage,
    archive: store,
    transport,
    origin: 'https://synthetic.invalid',
    database: 'trial',
    uuid: () => 'e458127f-777e-414f-ad44-256b06df8910',
  };
  let engine = new ChatEngine(options);
  await engine.login('synthetic', 'not-a-real-password', true);
  let window = await engine.history(room);
  const seen = new Set(window.messages.map(row => row.id));
  while (window.next_before_id !== null) {
    const first = window.messages[0]!.id;
    window = await engine.history(room, first);
    assert.ok(window.messages[0]!.id < first);
    assert.ok(window.messages.length <= 180);
    for (const row of window.messages) seen.add(row.id);
  }
  assert.equal(seen.size, 720);
  assert.equal(window.messages[0]?.id, 3);
  const oldIds = window.messages.map(row => row.id);
  source.push(message(2163));
  assert.deepEqual(
    (await engine.history(room)).messages.map(row => row.id),
    oldIds,
  );
  assert.equal((await engine.latest(room)).messages.at(-1)?.id, 2163);
  const beforeCached = gets;
  await engine.history(room, engine.rememberedHistory(room)!.messages[0]!.id);
  assert.equal(
    gets,
    beforeCached,
    'a proven local page does not refetch merely because another archive range was partial',
  );
  await engine.latest(room);
  assert.equal(
    (await engine.mediaAssociation(room, 70))?.id,
    6,
    'indexed association works outside hot window',
  );
  engine.markDisconnected();
  offline = true;
  await engine.enqueue(room, 'durable offline draft');
  const outbox = [...data.entries()].filter(([key]) => key.includes('/outbox/'));
  assert.equal(outbox.length, 1);
  engine = new ChatEngine(options);
  assert.equal(await engine.restoreOffline(), true);
  assert.equal(engine.pending().length, 1);
  assert.deepEqual(
    [...data.entries()].filter(([key]) => key.includes('/outbox/')),
    outbox,
  );
  const cached = await engine.history(room);
  assert.equal(cached.messages.at(-1)?.id, 2163);
  await engine.history(room, cached.messages[0]!.id);
  assert.equal(engine.offline, true);
  offline = false;
  await engine.logout();
  assert.equal(db.prepare('SELECT COUNT(*) AS count FROM archive_messages').get()?.count, 0);
  db.close();
});

test(
  'capacity: actual 200k-row ten-room SQLite archive, bounded paging and disk evidence',
  { skip: process.env.BWORK_ARCHIVE_BENCH !== '1' },
  async () => {
    const directory = mkdtempSync(join(tmpdir(), 'bwork-archive-bench-'));
    const path = join(directory, 'archive.db');
    const { store, db, operations } = harness(path);
    const started = performance.now();
    try {
      for (let room = 0; room < 10; room++) {
        const selected = { ...scope, roomId: room + 1, membershipId: room + 100 };
        let before: number | null = null;
        for (let end = 20000; end > 0; end -= 30) {
          const ids = Array.from(
            { length: Math.min(30, end) },
            (_, index) => (Math.max(0, end - 30) + index + 1) * 3,
          );
          const page = history(ids, end <= 30);
          page.messages = page.messages.map(row => ({
            ...row,
            text: `${row.text} ${'synthetic '.repeat(24)}`,
          }));
          await store.commitPage(selected, { beforeId: before, history: page }, guard);
          before = ids[0]!;
          operations.length = 0;
        }
      }
      const insertMs = performance.now() - started;
      const timings: number[] = [];
      let rows = 0,
        maxReturned = 0;
      for (let room = 0; room < 10; room++) {
        const selected = { ...scope, roomId: room + 1, membershipId: room + 100 };
        let anchor: number | undefined;
        for (;;) {
          const readAt = performance.now();
          const slice = await store.read(
            selected,
            anchor ? { ...latest, direction: 'before', anchorId: anchor } : latest,
            guard,
          );
          timings.push(performance.now() - readAt);
          rows += slice.messages.length;
          maxReturned = Math.max(maxReturned, slice.messages.length);
          if (slice.older.kind === 'end') break;
          assert.equal(slice.older.kind, 'cached');
          assert.ok(slice.messages.length);
          anchor = slice.messages[0]!.id;
          operations.length = 0;
        }
      }
      assert.equal(rows, 200000);
      assert.equal(maxReturned, 60);
      timings.sort((a, b) => a - b);
      db.exec('PRAGMA wal_checkpoint(TRUNCATE)');
      const evidence = {
        sqlite: db.prepare('SELECT sqlite_version() AS version').get()?.version,
        rows,
        rooms: 10,
        perRoom: 20000,
        insertMs: Math.round(insertMs),
        reads: timings.length,
        p50ms: Number(timings[Math.floor(timings.length * 0.5)]!.toFixed(3)),
        p95ms: Number(timings[Math.floor(timings.length * 0.95)]!.toFixed(3)),
        maxRowsReturned: maxReturned,
        databaseBytes: statSync(path).size,
        logicalBytes: db.prepare('SELECT SUM(byte_count) AS bytes FROM archive_scopes').get()
          ?.bytes,
        platform: process.platform,
        node: process.version,
        caveat: 'Synthetic local SQLite; not phone/network/server capacity certification',
      };
      console.log('ARCHIVE_SQLITE_CAPACITY', JSON.stringify(evidence));
      assert.ok(evidence.p95ms < 100, 'provisional host cached-page p95 target');
    } finally {
      db.close();
      rmSync(directory, { recursive: true, force: true });
    }
  },
);
