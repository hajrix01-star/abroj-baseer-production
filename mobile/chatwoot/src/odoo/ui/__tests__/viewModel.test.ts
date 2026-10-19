import type { Bootstrap, Room } from '../../core/ChatEngine';
import { companyActions, conversationAccess } from '../viewModel';
import { errorWord, translator } from '../dictionary';

const account = (permissions: Bootstrap['permissions'] = {}): Bootstrap => ({
  api_version: 2,
  database: 'synthetic',
  user_id: 7,
  company_ids: [1],
  permissions: {
    chat_view: true,
    chat_send: true,
    media: true,
    group_create: true,
    ...permissions,
  },
  mobile_policy: [{ api_version: 2, company_id: 1, direct_enabled: false, can_manage: false }],
});
const room: Room = {
  id: 10,
  company_id: 1,
  membership_id: 9,
  name: 'Synthetic room',
  is_group: true,
};

describe('Odoo chat presentation permissions without native imports', () => {
  test('read-only retains conversation but disables send and attachments', () => {
    expect(conversationAccess(account({ chat_send: false }), room)).toEqual({
      directOff: false,
      canSend: false,
      canAttach: false,
    });
    expect(conversationAccess(account({ media: false }), room)).toEqual({
      directOff: false,
      canSend: true,
      canAttach: false,
    });
  });
  test('DM policy only applies to explicit direct marker, not legacy non-group rooms', () => {
    expect(conversationAccess(account(), { ...room, is_group: false }).canSend).toBe(true);
    expect(
      conversationAccess(account(), { ...room, is_group: false, mobile_direct: true }),
    ).toEqual({ directOff: true, canSend: false, canAttach: false });
  });
  test('foreign company and missing identity cannot send or attach', () => {
    expect(conversationAccess(account(), { ...room, company_id: 2 }).canSend).toBe(false);
    expect(conversationAccess(null, room).canAttach).toBe(false);
  });
  test('enabled DM uses its company policy and does not imply group creation', () => {
    const identity = account({ group_create: false });
    identity.mobile_policy![0]!.direct_enabled = true;
    expect(companyActions(identity, 1, false)).toEqual({
      createGroup: false,
      direct: true,
      policy: false,
      disabled: false,
    });
    expect(companyActions(identity, 2, false)).toEqual({
      createGroup: false,
      direct: false,
      policy: false,
      disabled: false,
    });
  });
  test('offline disables server group/policy actions while text can be queued', () => {
    const identity = account();
    identity.mobile_policy![0]!.can_manage = true;
    expect(companyActions(identity, 1, true)).toEqual({
      createGroup: true,
      direct: false,
      policy: true,
      disabled: true,
    });
    expect(conversationAccess(identity, room).canSend).toBe(true);
  });
  test('permission values must be true rather than truthy client flags', () => {
    expect(conversationAccess(account({ chat_send: 1, media: 1 }), room).canSend).toBe(false);
    expect(companyActions(account({ group_create: 1 }), 1, false).createGroup).toBe(false);
  });
  test('errors give safe translated guidance rather than raw server messages', () => {
    expect(errorWord({ code: 'mfa_required', message: 'private detail' })).toBe('mfa');
    expect(errorWord({ code: 'file_too_large' })).toBe('tooLarge');
    expect(errorWord({ code: 'media_not_cached' })).toBe('mediaMissing');
    expect(errorWord({ code: 'offline_expired' })).toBe('expired');
    expect(errorWord({ code: 'arbitrary', message: 'password=synthetic' })).toBe('error');
    for (const language of ['ar', 'en'] as const) {
      expect(translator(language)('error')).not.toContain('synthetic');
      expect(translator(language)('mfa').length).toBeGreaterThan(10);
    }
  });
});
