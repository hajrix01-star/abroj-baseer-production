/** Sparse media pages are not history pages and never prove history coverage. */
import type { Message, Room } from './ChatEngine.ts';

export type GalleryKind = 'all' | 'image' | 'file' | 'audio';
export type GalleryOrder = 'newest' | 'oldest' | 'largest';
export interface MediaGalleryQuery { kind?: GalleryKind; order?: GalleryOrder; cursor?: string; limit?: number }
export interface MediaGalleryPage {
  api_version: 2; gallery_version: 1; room_id: number; company_id: number; membership_id: number;
  kind: GalleryKind; order: GalleryOrder; items: Message[]; next_cursor: string | null;
  /** Only describes a cached page, never complete server inventory. */
  cached?: boolean;
}
export const GALLERY_LIMITS = Object.freeze({ page: 30, maxPage: 60, bytes: 128 * 1024, associations: 180, cursor: 256 });
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0 && Number(v) < Number.MAX_SAFE_INTEGER;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const cursor = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= GALLERY_LIMITS.cursor && /^[A-Za-z0-9_-]+$/.test(v);
function fail(): never { throw new Error('invalid_gallery'); }

export function galleryQuery(query: MediaGalleryQuery = {}): Required<Omit<MediaGalleryQuery, 'cursor'>> & Pick<MediaGalleryQuery, 'cursor'> {
  if (!record(query) || Object.keys(query).some(key => !['kind', 'order', 'cursor', 'limit'].includes(key))) fail();
  const kind = query.kind ?? 'all', order = query.order ?? 'newest', limit = query.limit ?? GALLERY_LIMITS.page;
  if (typeof kind !== 'string' || typeof order !== 'string' || !['all', 'image', 'file', 'audio'].includes(kind) || !['newest', 'oldest', 'largest'].includes(order)
      || !positive(limit) || limit > GALLERY_LIMITS.maxPage || query.cursor !== undefined && !cursor(query.cursor)) fail();
  return { kind: kind as GalleryKind, order: order as GalleryOrder, limit, ...(query.cursor !== undefined ? { cursor: query.cursor } : {}) };
}

export function decodeGallery(raw: unknown, room: Room, requested: MediaGalleryQuery = {}): MediaGalleryPage {
  const query = galleryQuery(requested);
  if (!record(raw) || new TextEncoder().encode(JSON.stringify(raw)).length > GALLERY_LIMITS.bytes
      || raw.api_version !== 2 || raw.gallery_version !== 1 || raw.room_id !== room.id
      || raw.company_id !== room.company_id || raw.membership_id !== room.membership_id
      || raw.kind !== query.kind || raw.order !== query.order || !Array.isArray(raw.items)
      || raw.items.length > query.limit || raw.next_cursor !== null && !cursor(raw.next_cursor)
      || raw.next_cursor !== null && raw.items.length === 0 || raw.next_cursor !== null && raw.next_cursor === query.cursor) fail();
  const seen = new Set<number>(), mediaIds = new Set<number>();
  let previous: Message | undefined;
  for (const item of raw.items) {
    if (!record(item) || !positive(item.id) || !positive(item.author_user_id) || seen.has(item.id)
        || typeof item.author_name !== 'string' || item.author_name.length > 1024
        || typeof item.text !== 'string' || new TextEncoder().encode(item.text).length > 16384
        || typeof item.created_at !== 'string' || item.created_at.length > 64 || !Number.isFinite(Date.parse(item.created_at))
        || !record(item.media)) fail();
    const media = item.media;
    if (!positive(media.id) || mediaIds.has(media.id) || !['image', 'file', 'audio'].includes(String(media.kind))
        || query.kind !== 'all' && media.kind !== query.kind || !positive(media.size) || media.size > 10 * 1024 * 1024
        || typeof media.sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(media.sha256)
        || typeof media.mime !== 'string' || media.mime.length > 128 || typeof media.name !== 'string' || media.name.length > 1024
        || typeof media.thumbnail_available !== 'boolean' || typeof media.size_label !== 'string'
        || media.size_label.length > 40 || !/^[0-9]+(?:\.[0-9]{1,2})? (?:B|KiB|MiB)$/.test(media.size_label)) fail();
    if (previous) {
      const previousSize = Number(previous.media!.size);
      if (query.order === 'newest' && previous.id <= item.id || query.order === 'oldest' && previous.id >= item.id
          || query.order === 'largest' && (previousSize < media.size || previousSize === media.size && previous.id <= item.id)) fail();
    }
    seen.add(item.id); mediaIds.add(media.id); previous = item as unknown as Message;
  }
  return JSON.parse(JSON.stringify(raw)) as MediaGalleryPage;
}
