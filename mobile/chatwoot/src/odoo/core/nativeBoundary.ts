import { ChatError } from './ChatEngine.ts';
import type { History } from './ChatEngine.ts';

export const nativeSessionOptions = Object.freeze({ followRedirect: false, timeout: 30000, trusty: false });
export const actorPattern = /^[a-f0-9]{64}$/;
export const scopePattern = /^c([1-9]\d*)-r([1-9]\d*)-m([1-9]\d*)$/;
export const mediaFilePattern = /^(stage|media)-[a-zA-Z0-9.-]+$/;
export interface TrustedMedia { id: number; mime: string; size: number; sha256: string; kind: 'image' | 'file' | 'audio'; name: string }
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
