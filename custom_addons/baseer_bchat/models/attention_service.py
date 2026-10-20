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
            # The header only distinguishes 50 from 50+. Do not pull an
            # unbounded receipt history into Python just to calculate it.
            self.env.cr.execute('''
                SELECT COUNT(*)
                FROM (
                    SELECT 1
                    FROM baseer_bchat_message_receipt AS receipt
                    JOIN baseer_bchat_membership AS membership
                      ON membership.id = receipt.membership_id
                    WHERE receipt.membership_id = ANY(%s)
                      AND receipt.recipient_user_id = %s
                      AND receipt.read_at IS NULL
                      AND receipt.message_id > membership.joined_after_message_id
                      AND EXISTS (SELECT 1 FROM baseer_bchat_message m WHERE m.id=receipt.message_id AND m.retention_state='active')
                    LIMIT 51
                ) AS bounded_unread
            ''', [membership_ids, user.id])
            unread_messages = self.env.cr.fetchone()[0]
            # At most 51 recent receipts per active room are grouped. That
            # gives a useful 50+ count and a latest message while keeping the
            # request bounded at 100 rooms x 51 receipts.
            self.env.cr.execute('''
                WITH room_unread AS (
                    SELECT membership.id AS membership_id, receipt.message_id
                    FROM baseer_bchat_membership AS membership
                    JOIN LATERAL (
                        SELECT candidate.message_id
                        FROM baseer_bchat_message_receipt AS candidate
                        WHERE candidate.membership_id = membership.id
                          AND candidate.recipient_user_id = %s
                          AND candidate.read_at IS NULL
                          AND candidate.message_id > membership.joined_after_message_id
                          AND EXISTS (SELECT 1 FROM baseer_bchat_message m WHERE m.id=candidate.message_id AND m.retention_state='active')
                        ORDER BY candidate.message_id DESC
                        LIMIT 51
                    ) AS receipt ON TRUE
                    WHERE membership.id = ANY(%s)
                ), per_room AS (
                    SELECT membership_id, MAX(message_id) AS message_id,
                           COUNT(*) AS unread_count
                    FROM room_unread
                    GROUP BY membership_id
                )
                SELECT membership_id, message_id, unread_count
                FROM per_room
                ORDER BY message_id DESC
                LIMIT 25
            ''', [user.id, membership_ids])
            unread_rows = self.env.cr.fetchall()
            member_by_id = {member.id: member for member in memberships}
            latest_ids = [message_id for _membership_id, message_id, _count in unread_rows]
            latest = self.env['baseer.bchat.message'].sudo().browse(latest_ids).exists()
            by_id = {message.id: message for message in latest}
            for membership_id, message_id, unread_count in unread_rows:
                message = by_id.get(message_id)
                member = member_by_id.get(membership_id)
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
                    'unread_count': min(unread_count, 50),
                    'unread_overflow': unread_count > 50,
                })

        tasks, active_tasks = [], 0
        if permissions['task_view']:
            candidates = self.env['baseer.bchat.task'].sudo().search([
                '&', '&', '&',
                ('assignee_id', '=', user.id), ('company_id', 'in', company_ids),
                ('state', 'in', ('new', 'in_progress')),
                '|', ('room_id', '=', False), ('room_id', 'in', room_ids),
            ], order='id desc', limit=51)
            for task in candidates:
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
