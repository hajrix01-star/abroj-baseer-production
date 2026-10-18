import React, { useEffect, useState } from 'react';
import { Image, Text, View } from 'react-native';
import type { ChatEngine, Room } from '../core/ChatEngine';
import { clearGroupAvatars, hasGroupAvatar, readGroupAvatar, subscribeGroupAvatars, type GroupAvatarImage } from '../runtime';
import { colors } from './components';

/** The image is decorative by default; the adjacent room title already identifies it. */
export function GroupAvatar({ engine, room, enabled, size = 40, label }: {
  engine: ChatEngine; room: Room; enabled: boolean; size?: number; label?: string;
}) {
  const [image, setImage] = useState<(GroupAvatarImage & { token: string; owner: ChatEngine }) | null>(null);
  const identity = engine.identity;
  let permitted = false;
  try { permitted = enabled && identity?.permissions.chat_view === true && engine.rooms().some(row => row.id === room.id && row.company_id === room.company_id && row.membership_id === room.membership_id); } catch { /* Expired offline identity has no private image. */ }
  const token = `${engine.accountScope}/${identity?.database}/${identity?.user_id}/${room.company_id}/${room.id}/${room.membership_id}/${room.avatar_version ?? 0}/${permitted}`;
  useEffect(() => {
    let live = true;
    setImage(null);
    if (!enabled) clearGroupAvatars();
    const unsubscribe = subscribeGroupAvatars(() => { if (live) setImage(previous => previous && !hasGroupAvatar(previous.key) ? null : previous); });
    if (permitted && room.is_group && (room.avatar_version ?? 0) > 0) {
      void readGroupAvatar(engine, room).then(value => { if (live && hasGroupAvatar(value.key)) setImage({ ...value, token, owner: engine }); }).catch(() => { if (live) setImage(null); });
    }
    return () => { live = false; unsubscribe(); };
  }, [engine, token, enabled, permitted]);
  const diameter = Math.max(24, Math.min(96, size));
  const visible = permitted && image?.owner === engine && image.token === token && hasGroupAvatar(image.key);
  return <View accessible={!!label} accessibilityLabel={label} style={{ width: diameter, height: diameter, borderRadius: diameter / 2, overflow: 'hidden', backgroundColor: colors.pale, alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
    {visible ? <Image accessible={false} source={{ uri: image.uri }} resizeMode="cover" onError={() => setImage(null)} style={{ width: diameter, height: diameter }} />
      : <Text accessible={false} style={{ color: colors.blue, fontSize: Math.round(diameter * 0.4), fontWeight: '600' }}>{Array.from(room.name.trim())[0] ?? ''}</Text>}
  </View>;
}
