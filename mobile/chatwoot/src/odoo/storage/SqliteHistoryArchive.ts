/** Indexed, replaceable private cache. Odoo and ChatEngine remain the authority. */
import type { History, Message } from '../core/ChatEngine.ts';
import {
  ARCHIVE_LIMITS,
  ArchiveError,
  archiveScopeKey,
  mergeCoverage,
  pageCoverage,
  validateArchiveQuery,
} from '../core/HistoryArchive.ts';
import type {
  ArchiveEdge,
  ArchiveQuery,
  ArchiveSlice,
  Guard,
  HistoryArchive,
  HistoryScope,
} from '../core/HistoryArchive.ts';

type Value = string | number | null;
export interface ArchiveDatabase {
  execAsync(sql: string): Promise<void>;
  runAsync(sql: string, ...values: Value[]): Promise<unknown>;
  getFirstAsync<T>(sql: string, ...values: Value[]): Promise<T | null>;
  getAllAsync<T>(sql: string, ...values: Value[]): Promise<T[]>;
}
export interface MediaCacheEntry {
  uri: string;
  bytes: number;
  sha256: string;
  usedAt: number;
}
export interface MediaCacheCatalog {
  list(actor: string): Promise<MediaCacheEntry[]>;
  put(actor: string, entry: MediaCacheEntry): Promise<void>;
  remove(actor: string, uri: string): Promise<void>;
  touch(actor: string, uri: string, at: number): Promise<void>;
}
interface State {
  latest_id: number | null;
  verified: number;
  row_count: number;
  byte_count: number;
}
interface Range {
  low: number;
  high: number;
}
interface Row {
  message_id: number;
  json: string;
  bytes: number;
}
const schema = `
PRAGMA journal_mode=WAL;
PRAGMA secure_delete=ON;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA journal_size_limit=8388608;
PRAGMA wal_autocheckpoint=256;
CREATE TABLE IF NOT EXISTS archive_scopes (
 account TEXT NOT NULL, scope TEXT NOT NULL, latest_id INTEGER, verified INTEGER NOT NULL DEFAULT 0,
 touched INTEGER NOT NULL, row_count INTEGER NOT NULL DEFAULT 0, byte_count INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(account,scope)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS archive_lru ON archive_scopes(account,touched,scope);
CREATE TABLE IF NOT EXISTS archive_messages (
 account TEXT NOT NULL, scope TEXT NOT NULL, message_id INTEGER NOT NULL, media_id INTEGER,
 json TEXT NOT NULL, bytes INTEGER NOT NULL,
 PRIMARY KEY(account,scope,message_id),
 FOREIGN KEY(account,scope) REFERENCES archive_scopes(account,scope) ON DELETE CASCADE
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS archive_media ON archive_messages(account,scope,media_id,message_id);
CREATE TABLE IF NOT EXISTS archive_coverage (
 account TEXT NOT NULL, scope TEXT NOT NULL, low INTEGER NOT NULL, high INTEGER NOT NULL,
 PRIMARY KEY(account,scope,low),
 FOREIGN KEY(account,scope) REFERENCES archive_scopes(account,scope) ON DELETE CASCADE
) WITHOUT ROWID;
CREATE TRIGGER IF NOT EXISTS archive_insert AFTER INSERT ON archive_messages BEGIN
 UPDATE archive_scopes SET row_count=row_count+1,byte_count=byte_count+NEW.bytes WHERE account=NEW.account AND scope=NEW.scope;
END;
CREATE TRIGGER IF NOT EXISTS archive_delete AFTER DELETE ON archive_messages BEGIN
 UPDATE archive_scopes SET row_count=row_count-1,byte_count=byte_count-OLD.bytes WHERE account=OLD.account AND scope=OLD.scope;
END;
CREATE TRIGGER IF NOT EXISTS archive_update AFTER UPDATE OF bytes ON archive_messages BEGIN
 UPDATE archive_scopes SET byte_count=byte_count-OLD.bytes+NEW.bytes WHERE account=NEW.account AND scope=NEW.scope;
END;
CREATE TABLE IF NOT EXISTS media_cache (
 actor TEXT NOT NULL, uri TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, used_at INTEGER NOT NULL,
 PRIMARY KEY(actor,uri)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS media_cache_lru ON media_cache(actor,used_at,uri);
PRAGMA user_version=1;
`;
const encoder = new TextEncoder();
const noop = () => {};
const cloneMessage = (row: Row): Message => {
  try {
    const value = JSON.parse(row.json) as Message;
    if (
      value.id !== row.message_id ||
      !Number.isSafeInteger(value.id) ||
      typeof value.text !== 'string' ||
      typeof value.author_name !== 'string' ||
      typeof value.created_at !== 'string' ||
      !Number.isSafeInteger(value.author_user_id)
    )
      throw new Error();
    return value;
  } catch {
    throw new ArchiveError('invalid_archive_row');
  }
};
function encodeRows(messages: Message[]): (Row & { media_id: number | null })[] {
  let previous = 0;
  return messages.map(message => {
    const json = JSON.stringify(message);
    const bytes = encoder.encode(json).length;
    if (
      !Number.isSafeInteger(message.id) ||
      message.id <= previous ||
      message.id >= Number.MAX_SAFE_INTEGER ||
      bytes > ARCHIVE_LIMITS.windowBytes
    )
      throw new ArchiveError('invalid_archive_row');
    previous = message.id;
    cloneMessage({ message_id: message.id, json, bytes });
    const media = message.media?.id;
    return {
      message_id: message.id,
      json,
      bytes,
      media_id: Number.isSafeInteger(media) && Number(media) > 0 ? Number(media) : null,
    };
  });
}

/** All archive/catalog calls share this queue; no query can join another caller's transaction. */
export class SqliteArchiveStore implements HistoryArchive {
  private work: Promise<unknown> = Promise.resolve();
  private database: Promise<ArchiveDatabase> | undefined;
  private tick = 0;
  private readonly open: () => Promise<ArchiveDatabase>;
  private readonly limits: { accountMessages: number; accountBytes: number };
  readonly mediaCacheCatalog: MediaCacheCatalog;
  constructor(
    open: () => Promise<ArchiveDatabase>,
    limits = {
      accountMessages: ARCHIVE_LIMITS.accountMessages as number,
      accountBytes: ARCHIVE_LIMITS.accountBytes as number,
    },
  ) {
    this.open = open;
    this.limits = limits;
    this.mediaCacheCatalog = {
      list: actor => this.catalogList(actor),
      put: (actor, entry) => this.catalogPut(actor, entry),
      remove: (actor, uri) =>
        this.serial(noop, async db => {
          this.actor(actor);
          await db.runAsync('DELETE FROM media_cache WHERE actor=? AND uri=?', actor, uri);
        }),
      touch: (actor, uri, at) =>
        this.serial(noop, async db => {
          this.actor(actor);
          if (!Number.isSafeInteger(at) || at < 0) throw new ArchiveError('invalid_media_cache');
          await db.runAsync(
            'UPDATE media_cache SET used_at=? WHERE actor=? AND uri=?',
            at,
            actor,
            uri,
          );
        }),
    };
  }
  private async db(): Promise<ArchiveDatabase> {
    if (!this.database)
      this.database = (async () => {
        const db = await this.open();
        const version = await db.getFirstAsync<{ user_version: number }>('PRAGMA user_version');
        if (version && version.user_version > 1) throw new ArchiveError('archive_schema_newer');
        await db.execAsync(schema);
        return db;
      })().catch(error => {
        this.database = undefined;
        throw error;
      });
    return this.database;
  }
  private serial<T>(guard: Guard, operation: (db: ArchiveDatabase) => Promise<T>): Promise<T> {
    const task = this.work.then(async () => {
      guard();
      const db = await this.db();
      guard();
      const result = await operation(db);
      guard();
      return result;
    });
    this.work = task.catch(noop);
    return task;
  }
  private tx<T>(
    guard: Guard,
    operation: (db: ArchiveDatabase) => Promise<T>,
    checkpoint = false,
  ): Promise<T> {
    return this.serial(guard, async raw => {
      let committed = false;
      const checked = async <R>(request: Promise<R>): Promise<R> => {
        const result = await request;
        guard();
        return result;
      };
      const db: ArchiveDatabase = {
        execAsync: sql => checked(raw.execAsync(sql)),
        runAsync: (sql, ...values) => checked(raw.runAsync(sql, ...values)),
        getFirstAsync: <R>(sql: string, ...values: Value[]) =>
          checked(raw.getFirstAsync<R>(sql, ...values)),
        getAllAsync: <R>(sql: string, ...values: Value[]) =>
          checked(raw.getAllAsync<R>(sql, ...values)),
      };
      await raw.execAsync('BEGIN IMMEDIATE');
      try {
        guard();
        const result = await operation(db);
        guard();
        await raw.execAsync('COMMIT');
        committed = true;
        guard();
        if (checkpoint) {
          await raw.execAsync('PRAGMA wal_checkpoint(TRUNCATE)');
          guard();
        }
        return result;
      } catch (error) {
        if (!committed) await raw.execAsync('ROLLBACK').catch(noop);
        throw error;
      }
    });
  }
  private scope(scope: HistoryScope): [string, string] {
    return [scope.account, archiveScopeKey(scope)];
  }
  private async ensure(db: ArchiveDatabase, scope: HistoryScope): Promise<void> {
    await db.runAsync(
      'INSERT INTO archive_scopes(account,scope,touched) VALUES(?,?,?) ON CONFLICT(account,scope) DO UPDATE SET touched=excluded.touched',
      ...this.scope(scope),
      Date.now() + this.tick++,
    );
  }
  private async rows(
    db: ArchiveDatabase,
    scope: HistoryScope,
    rows: ReturnType<typeof encodeRows>,
    ignoreExisting = false,
  ): Promise<void> {
    for (let start = 0; start < rows.length; start += 50) {
      const batch = rows.slice(start, start + 50);
      const values: Value[] = [];
      for (const row of batch)
        values.push(...this.scope(scope), row.message_id, row.media_id, row.json, row.bytes);
      await db.runAsync(
        `INSERT INTO archive_messages(account,scope,message_id,media_id,json,bytes) VALUES ${batch.map(() => '(?,?,?,?,?,?)').join(',')}
        ON CONFLICT(account,scope,message_id) DO ${ignoreExisting ? 'NOTHING' : 'UPDATE SET media_id=excluded.media_id,json=excluded.json,bytes=excluded.bytes'}`,
        ...values,
      );
    }
  }
  private async quota(
    db: ArchiveDatabase,
    scope: HistoryScope,
    incoming: ReturnType<typeof encodeRows>,
  ): Promise<boolean> {
    const totals = await db.getFirstAsync<{ count: number; bytes: number }>(
      'SELECT COALESCE(SUM(row_count),0) AS count,COALESCE(SUM(byte_count),0) AS bytes FROM archive_scopes WHERE account=?',
      scope.account,
    );
    while (
      totals &&
      (totals.count > this.limits.accountMessages || totals.bytes > this.limits.accountBytes)
    ) {
      const victim = await db.getFirstAsync<{
        scope: string;
        row_count: number;
        byte_count: number;
      }>(
        'SELECT scope,row_count,byte_count FROM archive_scopes WHERE account=? AND scope<>? ORDER BY touched,scope LIMIT 1',
        ...this.scope(scope),
      );
      if (victim) {
        await db.runAsync(
          'DELETE FROM archive_scopes WHERE account=? AND scope=?',
          scope.account,
          victim.scope,
        );
        totals.count -= victim.row_count;
        totals.bytes -= victim.byte_count;
      } else {
        // Cache reset invalidates ALL continuity. The remote archive remains accessible.
        await db.runAsync(
          'DELETE FROM archive_messages WHERE account=? AND scope=?',
          ...this.scope(scope),
        );
        await db.runAsync(
          'DELETE FROM archive_coverage WHERE account=? AND scope=?',
          ...this.scope(scope),
        );
        const bytes = incoming.reduce((sum, row) => sum + row.bytes, 0);
        if (incoming.length > this.limits.accountMessages || bytes > this.limits.accountBytes)
          throw new ArchiveError('archive_quota');
        await this.rows(db, scope, incoming);
        return true;
      }
    }
    return false;
  }
  async commitPage(
    scope: HistoryScope,
    page: { beforeId: number | null; history: History },
    guard: Guard,
  ): Promise<void> {
    const proof = pageCoverage(page.beforeId, page.history);
    const rows = encodeRows(page.history.messages);
    this.scope(scope);
    await this.tx(guard, async db => {
      await this.ensure(db, scope);
      if (proof.emptyLatest) {
        await db.runAsync(
          'DELETE FROM archive_messages WHERE account=? AND scope=?',
          ...this.scope(scope),
        );
        await db.runAsync(
          'DELETE FROM archive_coverage WHERE account=? AND scope=?',
          ...this.scope(scope),
        );
      } else {
        const ids = rows.map(row => row.message_id);
        await db.runAsync(
          `DELETE FROM archive_messages WHERE account=? AND scope=? AND message_id>=? ${proof.replaceHigh === null ? '' : 'AND message_id<?'} ${ids.length ? `AND message_id NOT IN (${ids.map(() => '?').join(',')})` : ''}`,
          ...this.scope(scope),
          proof.replaceLow,
          ...(proof.replaceHigh === null ? [] : [proof.replaceHigh]),
          ...ids,
        );
        await this.rows(db, scope, rows);
        if (proof.range) {
          const overlaps = await db.getAllAsync<Range>(
            'SELECT low,high FROM archive_coverage WHERE account=? AND scope=? AND high>=? AND low<=? ORDER BY low',
            ...this.scope(scope),
            proof.range.low,
            proof.range.high,
          );
          const merged = mergeCoverage([...overlaps, proof.range])[0]!;
          await db.runAsync(
            'DELETE FROM archive_coverage WHERE account=? AND scope=? AND high>=? AND low<=?',
            ...this.scope(scope),
            proof.range.low,
            proof.range.high,
          );
          await db.runAsync(
            'INSERT INTO archive_coverage(account,scope,low,high) VALUES(?,?,?,?)',
            ...this.scope(scope),
            merged.low,
            merged.high,
          );
        }
      }
      if (page.beforeId === null)
        await db.runAsync(
          'UPDATE archive_scopes SET latest_id=?,verified=1 WHERE account=? AND scope=?',
          proof.latestId,
          ...this.scope(scope),
        );
      const reset = await this.quota(db, scope, rows);
      if (reset && proof.range)
        await db.runAsync(
          'INSERT INTO archive_coverage(account,scope,low,high) VALUES(?,?,?,?)',
          ...this.scope(scope),
          proof.range.low,
          proof.range.high,
        );
    });
  }
  async importLegacy(scope: HistoryScope, history: History, guard: Guard): Promise<void> {
    if (history.api_version !== 2 || history.messages.length > 500)
      throw new ArchiveError('invalid_history');
    const rows = encodeRows(history.messages);
    if (rows.reduce((sum, row) => sum + row.bytes, 0) > 512 * 1024)
      throw new ArchiveError('invalid_history');
    await this.tx(guard, async db => {
      await this.ensure(db, scope);
      // No inferred coverage: historical v1 merged caches can contain internal holes.
      await this.rows(db, scope, rows, true);
      if (rows.length)
        await db.runAsync(
          'UPDATE archive_scopes SET latest_id=MAX(COALESCE(latest_id,0),?) WHERE account=? AND scope=? AND verified=0',
          rows.at(-1)!.message_id,
          ...this.scope(scope),
        );
      await this.quota(db, scope, rows);
    });
  }
  async read(scope: HistoryScope, query: ArchiveQuery, guard: Guard): Promise<ArchiveSlice> {
    validateArchiveQuery(query);
    this.scope(scope);
    return this.tx(guard, async db => {
      const state = await db.getFirstAsync<State>(
        'SELECT latest_id,verified,row_count,byte_count FROM archive_scopes WHERE account=? AND scope=?',
        ...this.scope(scope),
      );
      const cursor = query.anchorId ?? state?.latest_id ?? null;
      const missing: ArchiveEdge = { kind: 'fetch', cursor };
      if (!state)
        return {
          messages: [],
          older: missing,
          newer: { kind: 'fetch', cursor: null },
          latestId: null,
          partial: true,
          unverified: false,
        };
      if (state.verified && state.latest_id === null)
        return {
          messages: [],
          older: { kind: 'end', cursor: null },
          newer: { kind: 'end', cursor: null },
          latestId: null,
          partial: false,
          unverified: false,
        };
      if (
        query.direction === 'latest' &&
        state.latest_id !== null &&
        !(await db.getFirstAsync(
          'SELECT 1 FROM archive_messages WHERE account=? AND scope=? AND message_id=?',
          ...this.scope(scope),
          state.latest_id,
        ))
      ) {
        return {
          messages: [],
          older: { kind: 'fetch', cursor: state.latest_id },
          newer: { kind: 'gap', cursor: state.latest_id },
          latestId: state.latest_id,
          partial: true,
          unverified: false,
        };
      }
      const range =
        cursor === null
          ? null
          : await db.getFirstAsync<Range>(
              `SELECT low,high FROM archive_coverage WHERE account=? AND scope=? AND low${query.direction === 'before' ? '<' : '<='}? AND high${query.direction === 'before' ? '>=' : '>'}? ORDER BY low DESC LIMIT 1`,
              ...this.scope(scope),
              cursor,
              cursor,
            );
      const values: Value[] = [...this.scope(scope)];
      let where = '';
      if (range) {
        where += ' AND message_id>=? AND message_id<?';
        values.push(range.low, range.high);
      }
      if (query.direction === 'before') {
        where += ' AND message_id<?';
        values.push(query.anchorId!);
      }
      if (query.direction === 'after') {
        where += ' AND message_id>?';
        values.push(query.anchorId!);
      }
      if (query.direction === 'latest' && state.latest_id !== null) {
        where += ' AND message_id<=?';
        values.push(state.latest_id);
      }
      const ascending = query.direction === 'after';
      const candidates = await db.getAllAsync<Row>(
        `SELECT message_id,json,bytes FROM archive_messages WHERE account=? AND scope=? ${where} ORDER BY message_id ${ascending ? 'ASC' : 'DESC'} LIMIT ?`,
        ...values,
        query.limit + 1,
      );
      let bytes = 2;
      const selected: Row[] = [];
      for (const row of candidates) {
        const addition = row.bytes + (selected.length ? 1 : 0);
        if (selected.length === query.limit || bytes + addition > query.maxBytes) break;
        selected.push(row);
        bytes += addition;
      }
      if (candidates.length && !selected.length) throw new ArchiveError('archive_row_too_large');
      if (!ascending) selected.reverse();
      const first = selected[0]?.message_id ?? cursor;
      const last = selected.at(-1)?.message_id ?? cursor;
      const hasOlder =
        first === null
          ? false
          : !!(await db.getFirstAsync(
              'SELECT 1 FROM archive_messages WHERE account=? AND scope=? AND message_id<? AND message_id>=? LIMIT 1',
              ...this.scope(scope),
              first,
              range?.low ?? 0,
            ));
      const hasNewer =
        last === null
          ? false
          : !!(await db.getFirstAsync(
              'SELECT 1 FROM archive_messages WHERE account=? AND scope=? AND message_id>? AND message_id<? LIMIT 1',
              ...this.scope(scope),
              last,
              range?.high ?? Number.MAX_SAFE_INTEGER,
            ));
      // Separate range probes preserve keyset index seeks; an OR can scan the whole room.
      const outside = range
        ? !!(await db.getFirstAsync(
            'SELECT 1 FROM archive_messages WHERE account=? AND scope=? AND message_id<? LIMIT 1',
            ...this.scope(scope),
            range.low,
          )) ||
          !!(await db.getFirstAsync(
            'SELECT 1 FROM archive_messages WHERE account=? AND scope=? AND message_id>=? LIMIT 1',
            ...this.scope(scope),
            range.high,
          ))
        : true;
      const edge = (direction: 'older' | 'newer'): ArchiveEdge => {
        const anchor = direction === 'older' ? first : last;
        if (direction === 'older' ? hasOlder : hasNewer) return { kind: 'cached', cursor: anchor };
        if (
          range &&
          (direction === 'older'
            ? range.low === 0
            : state.verified === 1 && (last === state.latest_id || state.latest_id === null))
        )
          return { kind: 'end', cursor: null };
        return { kind: !range || outside ? 'gap' : 'fetch', cursor: anchor };
      };
      await db.runAsync(
        'UPDATE archive_scopes SET touched=? WHERE account=? AND scope=?',
        Date.now() + this.tick++,
        ...this.scope(scope),
      );
      const older = edge('older'),
        newer = edge('newer');
      return {
        messages: selected.map(cloneMessage),
        older,
        newer,
        latestId: state.latest_id,
        partial: !range || older.kind === 'gap' || newer.kind === 'gap',
        unverified: !range && selected.length > 0,
      };
    });
  }
  async findMedia(scope: HistoryScope, mediaId: number, guard: Guard): Promise<Message | null> {
    if (!Number.isSafeInteger(mediaId) || mediaId <= 0)
      throw new ArchiveError('invalid_media_cache');
    return this.serial(guard, async db => {
      const row = await db.getFirstAsync<Row>(
        'SELECT message_id,json,bytes FROM archive_messages WHERE account=? AND scope=? AND media_id=? ORDER BY message_id DESC LIMIT 1',
        ...this.scope(scope),
        mediaId,
      );
      guard();
      return row ? cloneMessage(row) : null;
    });
  }
  async reconcile(
    account: string,
    allowedScopes: HistoryScope[],
    mediaAllowed: boolean,
    guard: Guard,
  ): Promise<void> {
    const allowed = new Set(
      allowedScopes.map(scope => {
        if (scope.account !== account) throw new ArchiveError('invalid_archive_scope');
        return archiveScopeKey(scope);
      }),
    );
    await this.tx(
      guard,
      async db => {
        const existing = await db.getAllAsync<{ scope: string }>(
          'SELECT scope FROM archive_scopes WHERE account=?',
          account,
        );
        for (const row of existing)
          if (!allowed.has(row.scope))
            await db.runAsync(
              'DELETE FROM archive_scopes WHERE account=? AND scope=?',
              account,
              row.scope,
            );
        if (!mediaAllowed)
          await db.runAsync(
            "UPDATE archive_messages SET json=json_remove(json,'$.media'),bytes=length(CAST(json_remove(json,'$.media') AS BLOB)),media_id=NULL WHERE account=? AND media_id IS NOT NULL",
            account,
          );
      },
      true,
    );
  }
  async purgeAccount(account: string, guard: Guard): Promise<void> {
    await this.tx(
      guard,
      async db => {
        await db.runAsync('DELETE FROM archive_scopes WHERE account=?', account);
      },
      true,
    );
  }
  private actor(actor: string): void {
    if (!/^[a-f0-9]{64}$/.test(actor)) throw new ArchiveError('invalid_media_cache');
  }
  private async catalogList(actor: string): Promise<MediaCacheEntry[]> {
    this.actor(actor);
    return this.serial(noop, db =>
      db.getAllAsync<MediaCacheEntry>(
        'SELECT uri,bytes,sha256,used_at AS usedAt FROM media_cache WHERE actor=? ORDER BY used_at,uri LIMIT 5001',
        actor,
      ),
    );
  }
  private async catalogPut(actor: string, entry: MediaCacheEntry): Promise<void> {
    this.actor(actor);
    if (
      !entry.uri.startsWith('file:///') ||
      entry.uri.length > 2048 ||
      !Number.isSafeInteger(entry.bytes) ||
      entry.bytes < 1 ||
      entry.bytes > 10 * 1024 * 1024 ||
      !/^[a-f0-9]{64}$/i.test(entry.sha256) ||
      !Number.isSafeInteger(entry.usedAt) ||
      entry.usedAt < 0
    )
      throw new ArchiveError('invalid_media_cache');
    await this.tx(noop, async db => {
      const count = await db.getFirstAsync<{ count: number }>(
        'SELECT COUNT(*) AS count FROM media_cache WHERE actor=?',
        actor,
      );
      const exists = await db.getFirstAsync(
        'SELECT 1 FROM media_cache WHERE actor=? AND uri=?',
        actor,
        entry.uri,
      );
      if (!exists && count && count.count >= 5000) throw new ArchiveError('media_quota');
      await db.runAsync(
        'INSERT INTO media_cache(actor,uri,bytes,sha256,used_at) VALUES(?,?,?,?,?) ON CONFLICT(actor,uri) DO UPDATE SET bytes=excluded.bytes,sha256=excluded.sha256,used_at=excluded.used_at',
        actor,
        entry.uri,
        entry.bytes,
        entry.sha256,
        entry.usedAt,
      );
    });
  }
}
