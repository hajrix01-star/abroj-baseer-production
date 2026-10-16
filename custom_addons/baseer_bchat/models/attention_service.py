"""A bounded, permission-scoped attention summary for the BChat header."""
from odoo import api, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError


class BChatAttentionService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_attention(self):
        """Return only the caller's unread rooms and assigned active tasks.

        The push-event ledger is deliberately not used here: it is device
        delivery state, while this is a durable per-user work queue.
        """
        user = self._require_any_bchat_permission('chat_view', 'task_view')
        permissions = user._bchat_effective_permissions()
        company_ids = user.company_ids.ids
        if len(company_ids) > 100:
            raise ProtocolError('too_many_companies', 'Company scope exceeds the supported limit.', 409)

        memberships = self.env['baseer.bchat.membership'].sudo().search([
            ('user_id', '=', user.id), ('active', '=', True),
            ('company_id', 'in', company_ids),
        ], order='room_id', limit=101)
        if len(memberships) > 100:
            raise ProtocolError('too_many_rooms', 'Attention listing needs room pagination.', 409)
        room_ids = sorted(set(memberships.mapped('room_id').ids))
        for room_id in room_ids:
            self._v2_lock_room(room_id)
        # The room locks make a leave/rejoin race a whole-request retry under
        # PostgreSQL's repeatable-read isolation. Re-reading avoids stale epochs.
        memberships = self.env['baseer.bchat.membership'].sudo().search([
            ('user_id', '=', user.id), ('active', '=', True),
            ('room_id', 'in', room_ids), ('company_id', 'in', company_ids),
        ])
        member_by_room = {member.room_id.id: member for member in memberships}
        membership_ids = memberships.ids

        messages, unread_messages = [], 0
        if permissions['chat_view'] and membership_ids:
            self.env.cr.execute('''
                SELECT receipt.membership_id, receipt.message_id, COUNT(*)
                FROM baseer_bchat_message_receipt AS receipt
                JOIN baseer_bchat_membership AS membership
                  ON membership.id = receipt.membership_id
                WHERE receipt.membership_id = ANY(%s)
                  AND receipt.recipient_user_id = %s
                  AND receipt.read_at IS NULL
                  AND receipt.message_id > membership.joined_after_message_id
                GROUP BY receipt.membership_id, receipt.message_id
                ORDER BY receipt.message_id DESC
            ''', [membership_ids, user.id])
            unread_rows = self.env.cr.fetchall()
            unread_messages = len(unread_rows)
            latest_by_member = {}
            for membership_id, message_id, _count in unread_rows:
                if membership_id not in latest_by_member:
                    latest_by_member[membership_id] = message_id
            latest_ids = list(latest_by_member.values())[:25]
            latest = self.env['baseer.bchat.message'].sudo().browse(latest_ids).exists()
            by_id = {message.id: message for message in latest}
            unread_by_member = {}
            for membership_id, _message_id, _count in unread_rows:
                unread_by_member[membership_id] = unread_by_member.get(membership_id, 0) + 1
            for membership_id, message_id in list(latest_by_member.items())[:25]:
                message = by_id.get(message_id)
                member = memberships.filtered(lambda row: row.id == membership_id)
                if not message or not member or member.room_id.id not in member_by_room:
                    continue
                preview = ' '.join((message.text or '').split())[:160]
                messages.append({
                    'room_id': member.room_id.id,
                    'company_id': member.company_id.id,
                    'room_name': member.room_id.name,
                    'message_id': message.id,
                    'author_name': self._task_label(message.author_user_id.name),
                    'preview': preview,
                    'unread_count': unread_by_member.get(membership_id, 0),
                })

        tasks, active_tasks = [], 0
        if permissions['task_view']:
            candidates = self.env['baseer.bchat.task'].sudo().search([
                ('assignee_id', '=', user.id), ('company_id', 'in', company_ids),
                ('state', 'in', ('new', 'in_progress')),
            ], order='id desc', limit=51)
            for task in candidates:
                if task.room_id and task.room_id.id not in member_by_room:
                    continue
                active_tasks += 1
                if len(tasks) < 25:
                    tasks.append(self._task_data(task))

        total = unread_messages + active_tasks
        return {
            'api_version': 2,
            'badge_count': min(total, 50),
            'badge_overflow': total > 50,
            'messages': messages,
            'tasks': tasks,
        }
