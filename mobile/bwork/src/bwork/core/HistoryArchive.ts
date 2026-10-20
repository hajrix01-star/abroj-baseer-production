import type { History, Message } from './ChatEngine.ts';

/** Durable namespace: credentials and session epochs never belong in this key. */
export interface HistoryScope { account: string; companyId: number; roomId: number; membershipId: number }
export type Guard = () => void;
export interface ArchiveEdge { kind: 'cached' | 'fetch' | 'gap' | 'end'; cursor: number | null }
export interface ArchiveSlice {
  messages: Message[];
  older: ArchiveEdge;
  newer: ArchiveEdge;
  latestId: number | null;
  /** Legacy imports and disconnected cached ranges must never imply complete history. */
  partial: boolean;
  /** Returned legacy rows lack proven INTERNAL continuity; online reads must revalidate. */
  unverified: boolean;
}
export interface ArchiveQuery { direction: 'latest' | 'before' | 'after'; anchorId?: number; limit: number; maxBytes: number }
export interface HistoryArchive {
  commitPage(scope: HistoryScope, page: { beforeId: number | null; history: History }, guard: Guard): Promise<void>;
  read(scope: HistoryScope, query: ArchiveQuery, guard: Guard): Promise<ArchiveSlice>;
  findMedia(scope: HistoryScope, mediaId: number, guard: Guard): Promise<Message | null>;
  retainMediaAssociation?(scope:HistoryScope,message:Message|null,mediaId:number,guard:Guard):Promise<void>;
  clearRoom?(scope:HistoryScope,guard:Guard):Promise<void>;
  importLegacy(scope: HistoryScope, history: History, guard: Guard): Promise<void>;
  reconcile(account: string, allowedScopes: HistoryScope[], mediaAllowed: boolean, guard: Guard): Promise<void>;
  purgeAccount(account: string, guard: Guard): Promise<void>;
}
export const ARCHIVE_LIMITS = Object.freeze({ windowMessages: 180, windowBytes: 512 * 1024, pageMessages: 60, pageBytes: 256 * 1024, accountMessages: 200000, accountBytes: 128 * 1024 * 1024 });
export interface CoverageRange { low: number; high: number }
export interface PageCoverage {
  range: CoverageRange | null;
  /** Remove cached rows absent from this authoritative half-open interval. null high = head. */
  replaceLow: number;
  replaceHigh: number | null;
  emptyLatest: boolean;
  /** Only update scope head when request beforeId is null. */
  latestId: number | null;
}
export class ArchiveError extends Error { readonly code: string; constructor(code: string) { super(code); this.code = code; this.name = 'ArchiveError'; } }
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0 && (value as number) < Number.MAX_SAFE_INTEGER;
export function archiveScopeKey(scope: HistoryScope): string {
  if (!scope.account || !positive(scope.companyId) || !positive(scope.roomId) || !positive(scope.membershipId)) throw new ArchiveError('invalid_archive_scope');
  return JSON.stringify([scope.account, scope.companyId, scope.roomId, scope.membershipId]);
}
/** The unchanged server returns ASC rows and its oldest returned ID iff more exists. */
export function pageCoverage(beforeId: number | null, history: History): PageCoverage {
  if (beforeId !== null && !positive(beforeId) || history.api_version !== 2 || !Array.isArray(history.messages)
      || history.messages.length > ARCHIVE_LIMITS.windowMessages || history.next_before_id !== null && !positive(history.next_before_id)) throw new ArchiveError('invalid_history');
  let last = 0;
  for (const message of history.messages) {
    if (!positive(message.id) || message.id <= last || beforeId !== null && message.id >= beforeId) throw new ArchiveError('invalid_history');
    last = message.id;
  }
  const first = history.messages[0]?.id;
  if (history.next_before_id !== null && (first === undefined || history.next_before_id !== first)) throw new ArchiveError('invalid_history_cursor');
  const low = history.next_before_id === null ? 0 : first!;
  const high = beforeId ?? (last ? last + 1 : 0);
  return { range: high > low ? { low, high } : null, replaceLow: low, replaceHigh: beforeId,
    emptyLatest: beforeId === null && !history.messages.length, latestId: last || null };
}
/** Proven intervals only. Legacy min/max rows MUST NOT be passed as coverage. */
export function mergeCoverage(ranges: readonly CoverageRange[]): CoverageRange[] {
  const result: CoverageRange[] = [];
  for (const value of [...ranges].sort((a, b) => a.low - b.low)) {
    if (!Number.isSafeInteger(value.low) || value.low < 0 || !positive(value.high) || value.high <= value.low) throw new ArchiveError('invalid_archive_coverage');
    const previous = result[result.length - 1];
    if (previous && value.low <= previous.high) previous.high = Math.max(previous.high, value.high);
    else result.push({ ...value });
  }
  return result;
}
export function validateArchiveQuery(query: ArchiveQuery): void {
  if (!['latest', 'before', 'after'].includes(query.direction) || !Number.isSafeInteger(query.limit) || query.limit < 1 || query.limit > ARCHIVE_LIMITS.windowMessages
      || !Number.isSafeInteger(query.maxBytes) || query.maxBytes < 2 || query.maxBytes > ARCHIVE_LIMITS.windowBytes
      || query.direction !== 'latest' && !positive(query.anchorId)) throw new ArchiveError('invalid_archive_query');
}
