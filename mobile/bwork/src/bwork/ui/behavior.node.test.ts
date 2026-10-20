import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Bootstrap, Room } from '../core/ChatEngine';
import { canViewMedia, conversationAccess, messageDateTime, messageTime, presentationKey, visibleReadIds } from './viewModel.ts';
import { errorWord, translator } from './dictionary.ts';

const identity: Bootstrap = {
  api_version: 2,
  database: 'synthetic',
  user_id: 7,
  company_ids: [1],
  permissions: { chat_view: true, chat_send: true, media: true, revision: 1 },
};
const room: Room = { id: 4, company_id: 1, membership_id: 9, name: 'Synthetic', is_group: true };
test('Odoo UTC message times convert to local zone with Latin digits and preserve explicit offsets', () => {
  assert.equal(messageTime('2026-10-18 12:30:00', 'Asia/Riyadh'), '15:30');
  assert.equal(messageTime('2026-10-18T15:30:00+03:00', 'Asia/Riyadh'), '15:30');
  assert.equal(messageTime('not-a-date', 'Asia/Riyadh'), '');
  assert.equal(messageDateTime('2026-10-18 12:30:00', 'Asia/Riyadh'), '18/10/2026, 15:30');
  assert.equal(messageDateTime('not-a-date', 'Asia/Riyadh'), '');
});
test('media permission and revision invalidate presentation identity without changing room', () => {
  const revoked = {
    ...identity,
    permissions: { ...identity.permissions, media: false, revision: 2 },
  };
  assert.equal(canViewMedia(identity, room), true);
  assert.equal(canViewMedia(revoked, room), false);
  assert.notEqual(presentationKey(identity, room), presentationKey(revoked, room));
  assert.equal(
    canViewMedia({ ...identity, permissions: { ...identity.permissions, chat_view: false } }, room),
    false,
  );
  assert.equal(
    conversationAccess(
      { ...identity, permissions: { ...identity.permissions, chat_send: false } },
      room,
    ).canAttach,
    false,
  );
});
test('read receipts select only actual visible non-own unique IDs, bounded to 20 and foreground', () => {
  const visible = Array.from({ length: 30 }, (_, i) => ({
    message: { id: i + 1, author_user_id: i === 0 ? 7 : 8 },
  }));
  assert.deepEqual(visibleReadIds(visible, 7, false), []);
  const ids = visibleReadIds([...visible, visible[1]!], 7, true);
  assert.equal(ids.length, 20);
  assert.equal(ids.includes(1), false);
  assert.equal(new Set(ids).size, 20);
});
test('safe UX text distinguishes credentials, MFA, local logout and queued send', () => {
  assert.equal(errorWord({ code: 'connection_failed' }), 'connectionError');
  assert.equal(translator('ar')('connectionError'), 'تعذر الاتصال بأودو. تحقق من اتصالك بالإنترنت ثم حاول مجددًا.');
  assert.equal(translator('en')('connectionError'), 'Could not reach Odoo. Check your internet connection and try again.');
  for (const language of ['ar', 'en'] as const) assert.doesNotMatch(translator(language)(errorWord({ code: 'connection_failed' })), /tailscale/i);
  assert.equal(errorWord({ code: 'authentication_failed' }), 'credentials');
  assert.equal(errorWord({ code: 'mfa_required' }), 'mfa');
  assert.equal(translator('ar')('queued'), 'بانتظار الإرسال');
  assert.ok(translator('ar')('pendingWarning').includes('أودو'));
  assert.equal(translator('ar')('mfa'), 'يتطلب حسابك تحققًا بخطوتين. هذا المسار غير متاح في الإصدار الحالي.');
  assert.equal(translator('en')('mfa'), 'Your account requires two-step verification. This flow is unavailable in the current build.');
  for (const language of ['ar', 'en'] as const) assert.doesNotMatch(translator(language)('mfa'), /trial|تجريب/i);
});
