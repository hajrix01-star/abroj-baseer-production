import { ChatError } from './ChatEngine.ts';
import type { History } from './ChatEngine.ts';

export const nativeSessionOptions = Object.freeze({ followRedirect: false, timeout: 30000, trusty: false });
export const actorPattern = /^[a-f0-9]{64}$/;
export const scopePattern = /^c([1-9]\d*)-r([1-9]\d*)-m([1-9]\d*)$/;
export const mediaFilePattern = /^(stage|media)-[a-zA-Z0-9.-]+$/;
export interface TrustedMedia { id: number; mime: string; size: number; sha256: string; kind: 'image' | 'file' | 'audio'; name: string; thumbnail_available?: boolean }

/** Bounded JPEG SOF parser. No full-resolution decode or unbounded base64 buffer. */
export function validThumbnail(raw: string): boolean {
  const byte = (at: number) => raw.charCodeAt(at);
  if (raw.length < 12 || raw.length > 128 * 1024 || byte(0) !== 255 || byte(1) !== 216
      || byte(raw.length - 2) !== 255 || byte(raw.length - 1) !== 217) return false;
  let at = 2, dimensions = false;
  while (at + 3 < raw.length) {
    if (byte(at++) !== 255) return false;
    while (byte(at) === 255) at++;
    const marker = byte(at++);
    if (marker === 218) return dimensions; // Native image decoder validates entropy when rendered.
    if ([0, 216, 217].includes(marker) || marker >= 208 && marker <= 215) return false;
    const length = byte(at) * 256 + byte(at + 1);
    if (length < 2 || at + length > raw.length - 2) return false;
    if ([192, 193, 194].includes(marker)) {
      if (dimensions || length < 8 || byte(at + 2) !== 8) return false;
      const height = byte(at + 3) * 256 + byte(at + 4), width = byte(at + 5) * 256 + byte(at + 6);
      if (height < 1 || height > 256 || width < 1 || width > 256) return false;
      dimensions = true;
    } else if (marker >= 192 && marker <= 207 && ![196, 200, 204].includes(marker)) return false;
    at += length;
  }
  return false;
}
export function retainNativeFile(input: { filename: string; mode: 'snapshot' | 'cacheOnly' | 'logout'; validIdentity: boolean; matchingScope: boolean; mediaRight: boolean; sendRight: boolean; pending: boolean; reserved: boolean }): boolean {
  if (input.filename.startsWith('stage-')) return input.mode !== 'logout' && (input.mode === 'cacheOnly' || !input.validIdentity || input.matchingScope && input.mediaRight && input.sendRight && (input.pending || input.reserved));
  return input.mode === 'snapshot' && input.matchingScope && input.mediaRight;
}

/** The descriptor only selects an ID. Every byte property comes from room history. */
export function trustedMedia(history: History, descriptor: Record<string, unknown>): TrustedMedia {
  const id = descriptor.id;
  if (!Number.isSafeInteger(id) || Number(id) <= 0) throw new ChatError('invalid_attachment');
  const media = history.messages.find(message => message.media?.id === id)?.media;
  if (!media || !['image', 'audio', 'file'].includes(String(media.kind)) || typeof media.mime !== 'string'
    || typeof media.name !== 'string' || !Number.isSafeInteger(media.size) || Number(media.size) <= 0
    || Number(media.size) > (media.kind === 'image' ? 5 : 10) * 1024 * 1024
    || typeof media.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(media.sha256)) throw new ChatError('media_room_mismatch', 403);
  return media as unknown as TrustedMedia;
}
