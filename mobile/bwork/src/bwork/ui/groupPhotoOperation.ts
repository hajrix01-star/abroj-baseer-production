import { AppState } from 'react-native';
import type { ImagePickerResponse } from 'react-native-image-picker';
import { ChatError, type ChatEngine, type GroupInfo, type Room } from '../core/ChatEngine';

export type GroupPhotoResult = { status: 'cancelled' } | { status: 'saved'; detail: GroupInfo };

/** Native picker results can precede Android's active event. Never upload while waiting. */
function foreground(): Promise<boolean> {
  if (AppState.currentState === 'active') return Promise.resolve(true);
  return new Promise(resolve => {
    let finished = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let subscription: { remove(): void } | undefined;
    const finish = (active: boolean) => {
      if (finished) return;
      finished = true; if (timer !== undefined) clearTimeout(timer); subscription?.remove(); resolve(active);
    };
    subscription = AppState.addEventListener('change', state => { if (state === 'active') finish(true); });
    if (finished) { subscription.remove(); return; }
    timer = setTimeout(() => finish(false), 5000);
    if (AppState.currentState === 'active') finish(true);
  });
}

/** Explicit user operation survives privacy-sheet unmount, never an account or membership change. */
export async function chooseGroupPhoto(engine: ChatEngine, value: Room, pick: () => Promise<ImagePickerResponse>): Promise<GroupPhotoResult> {
  const room = { ...value }, scope = engine.accountScope;
  const identity = engine.identity;
  const database = identity?.database, uid = identity?.user_id;
  const fence = () => {
    const current = engine.identity;
    if (!scope || engine.accountScope !== scope || !current || current.database !== database || current.user_id !== uid)
      throw new ChatError('stale_session');
    if (current.permissions.chat_view !== true || engine.offline || !engine.rooms().some(row =>
      row.is_group && row.id === room.id && row.company_id === room.company_id && row.membership_id === room.membership_id))
      throw new ChatError('membership_changed', 403);
  };
  fence();
  const chosen = await pick();
  if (chosen.didCancel) return { status: 'cancelled' };
  fence();
  if (chosen.errorCode) throw new ChatError('avatar_invalid');
  const asset = chosen.assets?.[0];
  if (!asset?.uri) return { status: 'cancelled' };
  if (!await foreground()) return { status: 'cancelled' };
  fence();
  if (AppState.currentState !== 'active') return { status: 'cancelled' };
  const detail = await engine.setGroupAvatar(room, { uri: asset.uri, name: asset.fileName ?? 'group.jpg', mime: asset.type ?? 'image/jpeg' });
  fence();
  return { status: 'saved', detail };
}
