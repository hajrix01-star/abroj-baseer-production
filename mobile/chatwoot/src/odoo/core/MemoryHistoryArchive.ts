import type { History, Message } from './ChatEngine.ts';
import { ARCHIVE_LIMITS, ArchiveError, archiveScopeKey, mergeCoverage, pageCoverage, validateArchiveQuery } from './HistoryArchive.ts';
import type { ArchiveEdge, ArchiveQuery, ArchiveSlice, CoverageRange, Guard, HistoryArchive, HistoryScope } from './HistoryArchive.ts';

type State = { scope: HistoryScope; rows: Map<number, Message>; ranges: CoverageRange[]; latestId: number | null; emptyVerified: boolean; touched: number };
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));
const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
const edge = (kind: ArchiveEdge['kind'], cursor: number | null = null): ArchiveEdge => ({ kind, cursor });

/** Pure/test fallback only. Android explicitly injects durable indexed SQLite. */
export class MemoryHistoryArchive implements HistoryArchive {
  private states = new Map<string, State>();
  private retained = new Map<string, { scope: HistoryScope; message: Message }>();
  private work: Promise<unknown> = Promise.resolve();
  private tick = 0;
  clearRoom(scope:HistoryScope,guard:Guard):Promise<void>{return this.run(guard,()=>{const key=archiveScopeKey(scope);this.states.delete(key);for(const [id,row]of this.retained)if(archiveScopeKey(row.scope)===key)this.retained.delete(id);});}
  private readonly limits: { messages: number; bytes: number };
  constructor(limits = { messages: 2000, bytes: 2 * 1024 * 1024 }) { this.limits = limits; }
  private run<T>(guard: Guard, operation: () => T): Promise<T> {
    const pending = this.work.then(() => { guard(); const result = operation(); guard(); return result; });
    this.work = pending.catch(() => undefined); return pending;
  }
  private state(scope: HistoryScope): State {
    const key = archiveScopeKey(scope);
    return this.states.get(key) ?? { scope: { ...scope }, rows: new Map(), ranges: [], latestId: null, emptyVerified: false, touched: 0 };
  }
  private commit(state: State, incoming: Message[], range: CoverageRange | null, guard: Guard): void {
    const all = new Map(this.states); state.touched = ++this.tick; all.set(archiveScopeKey(state.scope), state);
    const usage = () => [...all.values()].filter(row => row.scope.account === state.scope.account).reduce((sum, row) => {
      sum.messages += row.rows.size; for (const message of row.rows.values()) sum.bytes += bytes(message); return sum;
    }, { messages: 0, bytes: 0 });
    let total = usage();
    const others = [...all.entries()].filter(([key, row]) => row.scope.account === state.scope.account && key !== archiveScopeKey(state.scope)).sort((a, b) => a[1].touched - b[1].touched);
    for (const [key] of others) {
      if (total.messages <= this.limits.messages && total.bytes <= this.limits.bytes) break;
      all.delete(key); total = usage();
    }
    if (total.messages > this.limits.messages || total.bytes > this.limits.bytes) {
      state.rows = new Map(incoming.map(message => [message.id, copy(message)]));
      state.ranges = range ? [{ ...range }] : [];
      if (incoming.length > this.limits.messages || incoming.reduce((sum, row) => sum + bytes(row), 0) > this.limits.bytes) throw new ArchiveError('history_storage_full');
    }
    guard(); this.states = all;
  }
  commitPage(scope: HistoryScope, page: { beforeId: number | null; history: History }, guard: Guard): Promise<void> {
    return this.run(guard, () => {
      const coverage = pageCoverage(page.beforeId, page.history), old = this.state(scope);
      const state: State = { ...old, scope: { ...scope }, rows: new Map(old.rows), ranges: old.ranges.map(range => ({ ...range })) };
      if (coverage.emptyLatest) { state.rows.clear(); state.ranges = []; state.latestId = null; state.emptyVerified = true; }
      else {
        const ids = new Set(page.history.messages.map(row => row.id));
        for (const id of state.rows.keys()) if (id >= coverage.replaceLow && (coverage.replaceHigh === null || id < coverage.replaceHigh) && !ids.has(id)) state.rows.delete(id);
        for (const message of page.history.messages) state.rows.set(message.id, copy(message));
        state.ranges = mergeCoverage([...state.ranges, ...(coverage.range ? [coverage.range] : [])]);
        if (page.beforeId === null) { state.latestId = coverage.latestId; state.emptyVerified = false; }
      }
      this.commit(state, page.history.messages, coverage.range, guard);
    });
  }
  read(scope: HistoryScope, query: ArchiveQuery, guard: Guard): Promise<ArchiveSlice> {
    return this.run(guard, () => {
      validateArchiveQuery(query); const state = this.state(scope); state.touched = ++this.tick;
      const rows = [...state.rows.values()].sort((a, b) => a.id - b.id);
      const anchor = query.direction === 'latest' ? state.latestId ?? rows.at(-1)?.id : query.anchorId;
      if (query.direction === 'latest' && state.latestId !== null && !state.rows.has(state.latestId)) return { messages: [], older: edge('fetch', state.latestId), newer: edge('gap', state.latestId), latestId: state.latestId, partial: true, unverified: false };
      const range = anchor === undefined ? undefined : state.ranges.find(item => query.direction === 'before' ? item.low < anchor && item.high >= anchor : item.low <= anchor && item.high > anchor);
      const connected = range ? rows.filter(row => row.id >= range.low && row.id < range.high) : rows;
      let candidates = connected.filter(row => query.direction === 'before' ? row.id < query.anchorId! : query.direction === 'after' ? row.id > query.anchorId! : true);
      if (query.direction !== 'after') candidates = candidates.reverse();
      const selected: Message[] = []; let size = 2;
      for (const message of candidates) {
        const addition = bytes(message) + (selected.length ? 1 : 0);
        if (selected.length >= query.limit || size + addition > query.maxBytes) break;
        size += addition; selected.push(message);
      }
      if (query.direction !== 'after') selected.reverse();
      if (!selected.length && candidates.length) throw new ArchiveError('history_message_too_large');
      const first = selected[0]?.id ?? anchor, last = selected.at(-1)?.id ?? anchor;
      const older = first !== undefined && connected.some(row => row.id < first) ? edge('cached', first)
        : range?.low === 0 || state.emptyVerified ? edge('end')
          : edge(!range && rows.length > 0 || rows.some(row => first !== undefined && row.id < first) ? 'gap' : 'fetch', first ?? null);
      const newer = last !== undefined && connected.some(row => row.id > last) ? edge('cached', last)
        : !range && rows.length > 0 || state.latestId !== null && last !== undefined && state.latestId > last ? edge('gap', last ?? null) : edge('end');
      return { messages: copy(selected), older, newer, latestId: state.latestId ?? rows.at(-1)?.id ?? null, partial: !range && rows.length > 0 || older.kind === 'gap' || newer.kind === 'gap', unverified: !range && selected.length > 0 };
    });
  }
  findMedia(scope: HistoryScope, mediaId: number, guard: Guard): Promise<Message | null> {
    return this.run(guard, () => { const state = this.state(scope); return copy([...state.rows.values()].find(row => row.media?.id === mediaId) ?? this.retained.get(`${archiveScopeKey(scope)}media/${mediaId}`)?.message ?? null); });
  }
  retainMediaAssociation(scope: HistoryScope, message: Message | null, mediaId: number, guard: Guard): Promise<void> {
    return this.run(guard, () => {
      const next = new Map(this.retained), key = `${archiveScopeKey(scope)}media/${mediaId}`;
      if (message === null) next.delete(key);
      else {
        if (message.media?.id !== mediaId) throw new ArchiveError('invalid_history');
        next.set(key, { scope: { ...scope }, message: copy(message) });
        const rows = [...next.values()].filter(row => row.scope.account === scope.account);
        if (rows.length > 5000 || rows.reduce((sum, row) => sum + bytes(row), 0) > 8 * 1024 * 1024) throw new ArchiveError('history_storage_full');
      }
      guard(); this.retained = next;
    });
  }
  importLegacy(scope: HistoryScope, history: History, guard: Guard): Promise<void> {
    return this.run(guard, () => {
      if (!Array.isArray(history.messages) || history.messages.length > 500 || bytes(history) > ARCHIVE_LIMITS.windowBytes) throw new ArchiveError('invalid_history');
      const old = this.state(scope), state: State = { ...old, rows: new Map(old.rows), ranges: old.ranges.map(range => ({ ...range })) };
      for (const message of history.messages) if (!state.rows.has(message.id)) state.rows.set(message.id, copy(message));
      // No coverage is inferred, including INTERNAL gaps in a legacy merged cache.
      this.commit(state, history.messages, null, guard);
    });
  }
  reconcile(account: string, scopes: HistoryScope[], mediaAllowed: boolean, guard: Guard): Promise<void> {
    return this.run(guard, () => {
      const allowed = new Set(scopes.map(archiveScopeKey)), all = new Map(this.states);
      const retained = new Map(this.retained);
      for (const [key, row] of retained) if (row.scope.account === account && (!mediaAllowed || !allowed.has(archiveScopeKey(row.scope)))) retained.delete(key);
      for (const [key, old] of all) if (old.scope.account === account) {
        if (!allowed.has(key)) all.delete(key);
        else if (!mediaAllowed) {
          const rows = new Map<number, Message>();
          for (const [id, message] of old.rows) { const { media: _media, ...text } = message; rows.set(id, text); }
          all.set(key, { ...old, rows });
        }
      }
      guard(); this.states = all; this.retained = retained;
    });
  }
  purgeAccount(account: string, guard: Guard): Promise<void> {
    return this.run(guard, () => { const all = new Map(this.states), retained = new Map(this.retained); for (const [key, row] of all) if (row.scope.account === account) all.delete(key); for (const [key, row] of retained) if (row.scope.account === account) retained.delete(key); guard(); this.states = all; this.retained = retained; });
  }
}
