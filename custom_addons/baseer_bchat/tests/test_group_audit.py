"""C19 bounded directory, atomic selection and epoch-filtered metadata audit."""
import json
from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..contracts import ProtocolError


@tagged('post_install', '-at_install', 'baseer_bchat', 'bchat_group_audit')
class BChatGroupAuditCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.admin = self.env.ref('base.user_admin')
        self.admin.write({'group_ids': [Command.link(self.env.ref('baseer_bchat.group_bchat_manager').id)]})
        self.owner, self.reader = self._users(2, 'Group audit')
        self.service = self.env['baseer.bchat.service'].with_user(self.owner)
        created = self.service._v2_group_create({
            'api_version': 2, 'company_id': self.company.id, 'client_uuid': str(uuid4()),
            'name': 'Audited group', 'member_user_ids': [self.reader.id],
        })
        self.room = self.env['baseer.bchat.room'].sudo().browse(created['room_id'])
        self.membership_id = created['membership_id']
        self.events = self.env['baseer.bchat.group.event']

    def _users(self, count, prefix, company=None):
        selected = company or self.company
        return self.env['res.users'].with_context(no_reset_password=True).create([{
            'name': '%s %02d' % (prefix, number), 'login': 'bchat-group-audit-' + uuid4().hex,
            'company_id': selected.id, 'company_ids': [Command.set(selected.ids)],
            'group_ids': [Command.set([self.env.ref('base.group_user').id])],
        } for number in range(count)])

    def _batch(self, users, **extra):
        return {'api_version': 2, 'membership_id': self.membership_id,
                'client_uuid': str(uuid4()), 'user_ids': users.ids, **extra}

    def _detail(self):
        return self.service._v2_group_events(self.room.id, self.membership_id)

    def test_batch_add_is_one_atomic_audited_retry_and_hides_prior_messages(self):
        users = self._users(2, 'New group colleague')
        sent = self.service._v2_send(self.room.id, {'api_version': 2, 'membership_id': self.membership_id,
            'client_uuid': str(uuid4()), 'text': 'Before new epochs'})
        boundary = self.service._group_last_event_id(self.room)
        payload = self._batch(users)
        first = self.service._v2_group_add_members(self.room.id, payload)
        again = self.service._v2_group_add_members(self.room.id, payload)
        self.assertEqual(first['added_user_ids'], sorted(users.ids))
        self.assertTrue(again['replayed'])
        self.assertEqual(self.events.sudo().search_count([('room_id', '=', self.room.id), ('action', '=', 'add_members')]), 1)
        memberships = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('user_id', 'in', users.ids), ('active', '=', True)])
        self.assertEqual(len(memberships), 2)
        self.assertEqual(set(memberships.mapped('joined_after_message_id')), {sent['message_id']})
        self.assertEqual(set(memberships.mapped('joined_after_group_event_id')), {boundary})
        for user in users:
            self.assertEqual(self.env['baseer.bchat.service'].with_user(user)._v2_history(self.room.id)['messages'], [])

    def test_one_foreign_selection_rolls_back_the_entire_batch(self):
        good = self._users(1, 'Good selection')
        foreign_company = self.env['res.company'].create({'name': 'Audit foreign company'})
        foreign = self._users(1, 'Foreign selection', foreign_company)
        before = self.events.sudo().search_count([('room_id', '=', self.room.id)])
        with self.assertRaises(AccessError):
            self.service._v2_group_add_members(self.room.id, self._batch(good | foreign))
        self.assertFalse(self.env['baseer.bchat.membership'].sudo().search_count([
            ('room_id', '=', self.room.id), ('user_id', 'in', (good | foreign).ids)]))
        self.assertEqual(self.events.sudo().search_count([('room_id', '=', self.room.id)]), before)

    def test_batch_reaches_50_and_refuses_51_without_partial_memberships(self):
        additions = self._users(48, 'Bounded group')
        self.service._v2_group_add_members(self.room.id, self._batch(additions))
        self.assertEqual(self.env['baseer.bchat.membership'].sudo().search_count([
            ('room_id', '=', self.room.id), ('active', '=', True)]), 50)
        extra = self._users(1, 'Beyond limit')
        with self.assertRaises(ProtocolError) as full:
            self.service._v2_group_add_members(self.room.id, self._batch(extra))
        self.assertEqual(full.exception.code, 'too_many_members')
        self.assertFalse(self.env['baseer.bchat.membership'].sudo().search_count([
            ('room_id', '=', self.room.id), ('user_id', '=', extra.id)]))

    def test_new_administrator_cannot_read_audit_before_the_join_boundary(self):
        self.service._v2_group_change(self.room.id, {'api_version': 2, 'action': 'rename', 'name': 'Earlier name'})
        before_join = self.service._group_last_event_id(self.room)
        newcomer = self._users(1, 'New administrator')
        self.service._v2_group_add_members(self.room.id, self._batch(newcomer))
        self.service._v2_group_change(self.room.id, {'api_version': 2, 'action': 'promote_admin', 'user_id': newcomer.id})
        member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('user_id', '=', newcomer.id), ('active', '=', True)])
        result = self.env['baseer.bchat.service'].with_user(newcomer)._v2_group_events(self.room.id, member.id)
        self.assertTrue(result['events'])
        self.assertTrue(all(row['id'] > before_join for row in result['events']))
        self.assertFalse(result['historical_actions_backfilled'])
        self.assertTrue(result['audit_started_at'])

    def test_audit_is_service_private_and_room_admin_does_not_gain_history(self):
        for user in (self.owner, self.reader, self.admin):
            with self.subTest(user=user.id), self.assertRaises(AccessError):
                self.events.with_user(user).search_count([])
        reader_member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', self.room.id), ('user_id', '=', self.reader.id), ('active', '=', True)])
        with self.assertRaises(AccessError):
            self.env['baseer.bchat.service'].with_user(self.reader)._v2_group_events(self.room.id, reader_member.id)
        manager = self.env['baseer.bchat.service'].with_user(self.admin)
        self.assertEqual(manager._v2_group_events(self.room.id)['events'][0]['action'], 'create')
        with self.assertRaises(AccessError):
            manager._v2_history(self.room.id)

    def test_admin_add_revoke_and_rename_audit_has_actual_actor(self):
        colleague = self._users(1, 'Admin-added colleague')
        member = self.env['baseer.bchat.membership'].with_user(self.admin).create({
            'room_id': self.room.id, 'user_id': colleague.id})
        self.room.with_user(self.admin).write({'name': 'Administrative rename'})
        member.with_user(self.admin).action_revoke()
        events = self._detail()['events']
        actions = {row['action'] for row in events if row['actor_user_id'] == self.admin.id}
        self.assertTrue({'add_member', 'remove_member', 'rename'} <= actions)
        self.assertTrue(all(row['actor_membership_id'] is None for row in events
                            if row['actor_user_id'] == self.admin.id))

    def test_audit_pagination_and_utf8_ceiling_do_not_skip_rows(self):
        for _index in range(44):
            self.service._group_record_event(self.room, 'rename', metadata={'name': '界' * 650})
        before, seen = None, []
        for _page in range(45):
            result = self.service._v2_group_events(self.room.id, self.membership_id, before)
            ids = [row['id'] for row in result['events']]
            self.assertFalse(set(ids) & set(seen))
            seen.extend(ids)
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 65536)
            if result['next_before_id'] is None:
                break
            self.assertEqual(result['next_before_id'], ids[-1])
            before = result['next_before_id']
        self.assertEqual(len(seen), 45)

    def test_directory_pages_names_only_and_excludes_foreign_inactive_and_revoked(self):
        candidates = self._users(45, 'Directory candidate')
        hidden = self._users(2, 'Directory candidate hidden')
        hidden[0].write({'active': False})
        hidden[1].write({'bchat_chat_view': False})
        foreign_company = self.env['res.company'].create({'name': 'Directory foreign company'})
        foreign = self._users(1, 'Directory candidate foreign', foreign_company)
        first = self.service._v2_social_member_candidates(self.company.id, 'Directory candidate')
        self.assertEqual(len(first['users']), 40)
        second = self.service._v2_social_member_candidates(self.company.id, 'Directory candidate', first['next_after_user_id'])
        self.assertIsNone(second['next_after_user_id'])
        shown = [row['user_id'] for row in first['users'] + second['users']]
        self.assertEqual(shown, sorted(candidates.ids))
        self.assertFalse(set(shown) & set((hidden | foreign).ids))
        self.assertTrue(all(set(row) == {'user_id', 'name'} for row in first['users']))
