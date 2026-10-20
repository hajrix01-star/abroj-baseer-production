import type { Bootstrap, Room } from '../core/ChatEngine';

/** Odoo timestamps are UTC; display device-local time using 0–9 digits. */
export function messageTime(value: string, timeZone?: string): string {
  const iso = value.replace(' ', 'T');
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(iso) ? iso : `${iso}Z`);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', hour12: false, numberingSystem: 'latn', timeZone,
  }).format(date);
}

export function messageDateTime(value: string, timeZone?: string): string {
  const iso = value.replace(' ', 'T');
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(iso) ? iso : `${iso}Z`);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-GB', { year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false, numberingSystem: 'latn', timeZone }).format(date);
}

/** Server-derived presentation only; every operation remains server-authorized. */
export function conversationAccess(identity: Bootstrap | null, room: Room) {
  const scoped = !!identity?.company_ids.includes(room.company_id);
  const directOff =
    !!room.mobile_direct &&
    !identity?.mobile_policy?.find(policy => policy.company_id === room.company_id)?.direct_enabled;
  const canSend =
    scoped &&
    identity?.permissions.chat_view === true &&
    identity?.permissions.chat_send === true &&
    !directOff;
  return { directOff, canSend, canAttach: canSend && identity?.permissions.media === true };
}

export function canViewMedia(identity: Bootstrap | null, room: Room): boolean {
  return (
    !!identity?.company_ids.includes(room.company_id) &&
    identity.permissions.chat_view === true &&
    identity.permissions.media === true
  );
}

export function presentationKey(identity: Bootstrap | null, room: Room): string {
  return `${identity?.user_id}/${room.company_id}/${room.id}/${room.membership_id}/${identity?.permissions.revision}/${identity?.permissions.chat_view}/${identity?.permissions.chat_send}/${identity?.permissions.media}`;
}

export function visibleReadIds(
  items: { message?: { id: number; author_user_id: number } }[],
  userId: number,
  active: boolean,
): number[] {
  if (!active) return [];
  return [
    ...new Set(
      items
        .filter(item => item.message && item.message.author_user_id !== userId)
        .map(item => item.message!.id),
    ),
  ].slice(0, 20);
}

export function companyActions(identity: Bootstrap, companyId: number, offline: boolean) {
  const scoped = identity.company_ids.includes(companyId);
  const policy = identity.mobile_policy?.find(item => item.company_id === companyId);
  return {
    createGroup: scoped && identity.permissions.group_create === true,
    direct: scoped && policy?.direct_enabled === true && identity.permissions.chat_send === true,
    policy: scoped && policy?.can_manage === true,
    disabled: offline,
  };
}
