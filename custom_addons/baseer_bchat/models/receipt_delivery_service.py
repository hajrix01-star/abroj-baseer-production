"""C13 read-only discovery and sender projections over existing receipt rows.

Neither GET marks delivery nor creates recipients. A client must fetch canonical
data, commit/pin it locally, then use the existing authenticated receipt ACK.
"""
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import SQL

from ..contracts import ProtocolError, positive_id


PAGE_SIZE = 30
MAX_RESPONSE_BYTES = 65536
MAX_MEMBERSHIPS = 100


def _after_id(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise ProtocolError('invalid_payload', 'A nonnegative receipt cursor is required.')
    return value


def _bounded_page(base, key, rows, id_key):
    more = len(rows) > PAGE_SIZE
    page = rows[:PAGE_SIZE]
    while True:
        payload = {**base, key: page, 'next_after_id': page[-1][id_key] if page else 0,
                   'has_more': more}
        if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) <= MAX_RESPONSE_BYTES:
            return payload
        if not page:
            raise ProtocolError('page_too_large', 'Receipt metadata exceeds its supported byte bound.', 413)
        page = page[:-1]
        more = True
        if not page:
            raise ProtocolError('page_too_large', 'One receipt exceeds its supported byte bound.', 413)


class BChatReceiptDeliveryService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_receipt_summaries(self, message_ids):
        """Full current eligible totals shared by history and sender details."""
        ids = sorted(set(message_ids))
        if len(ids) > PAGE_SIZE:
            raise ProtocolError('invalid_payload', 'Receipt summary exceeds its message bound.')
        result = {message_id: {'state': 'sent', 'counts': {'eligible': 0, 'delivered': 0, 'read': 0},
                               'read_at': None} for message_id in ids}
        if not ids:
            return result
        eligible = self.env['baseer.bchat.message.receipt']._delivery_eligibility_sql()
        self.env.cr.execute(SQL('''
            SELECT r.message_id, COUNT(*), COUNT(r.delivered_at), COUNT(r.read_at), MAX(r.read_at)
            FROM baseer_bchat_message_receipt r
            JOIN baseer_bchat_membership m ON m.id=r.membership_id
            JOIN baseer_bchat_message msg ON msg.id=r.message_id
            JOIN res_users u ON u.id=r.recipient_user_id
            WHERE r.message_id=ANY(%s) AND %s GROUP BY r.message_id
        ''', ids, eligible))
        for message_id, count, delivered, read, completed_at in self.env.cr.fetchall():
            state = 'read' if count and read == count else 'delivered' if count and delivered == count else 'sent'
            result[message_id] = {'state': state, 'counts': {
                'eligible': count, 'delivered': delivered, 'read': read},
                'read_at': fields.Datetime.to_string(completed_at) if state == 'read' else None}
        return result

    @api.model
    def _v2_pending_receipts(self, after_id=0):
        user = self._require_bchat_permission('chat_view')
        after = _after_id(after_id)
        members = self.env['baseer.bchat.membership'].sudo().search([
            ('user_id', '=', user.id), ('active', '=', True),
            ('company_id', 'in', user.company_ids.ids)], order='id', limit=MAX_MEMBERSHIPS + 1)
        if len(members) > MAX_MEMBERSHIPS:
            raise ProtocolError('too_many_rooms', 'Receipt discovery needs membership pagination.', 409)
        for room_id in sorted(set(members.mapped('room_id').ids)):
            self.env['baseer.bchat.room']._lock_for_read(room_id)
        eligible = self.env['baseer.bchat.message.receipt']._delivery_eligibility_sql()
        rows = []
        if members:
            # Each index-driven candidate lane is bounded before the global merge.
            # Current eligibility is INSIDE each LIMIT, never a post-page filter.
            self.env.cr.execute(SQL('''
                SELECT candidate.id,candidate.room_id,candidate.membership_id,candidate.message_id
                FROM unnest(%s::integer[]) selected(membership_id)
                CROSS JOIN LATERAL (
                    SELECT r.id,msg.room_id,r.membership_id,r.message_id
                    FROM baseer_bchat_message_receipt r
                    JOIN baseer_bchat_membership m ON m.id=r.membership_id
                    JOIN baseer_bchat_message msg ON msg.id=r.message_id
                    JOIN res_users u ON u.id=r.recipient_user_id
                    WHERE r.recipient_user_id=%s AND r.membership_id=selected.membership_id
                      AND r.delivered_at IS NULL AND r.id>%s AND %s
                    ORDER BY r.id LIMIT 31
                ) candidate ORDER BY candidate.id LIMIT 31
            ''', members.ids, user.id, after, eligible))
            rows = [{'receipt_id': receipt_id, 'room_id': room_id,
                     'membership_id': member_id, 'message_id': message_id}
                    for receipt_id, room_id, member_id, message_id in self.env.cr.fetchall()]
        return _bounded_page({'api_version': 2}, 'refs', rows, 'receipt_id')

    @api.model
    def _v2_receipt_details(self, room_id, message_id, after_id=0):
        user = self._require_bchat_permission('chat_view')
        after = _after_id(after_id)
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        message_id = positive_id(message_id, 'message_id')
        message = self.env['baseer.bchat.message'].sudo().browse(message_id).exists()
        if (not message or message.room_id != room or message.company_id != room.company_id
                or message.author_user_id.id != user.id or message.id <= member.joined_after_message_id):
            raise AccessError(self.env._('This message receipt detail is unavailable.'))
        summary = self._v2_receipt_summaries([message.id])[message.id]
        eligible = self.env['baseer.bchat.message.receipt']._delivery_eligibility_sql()
        self.env.cr.execute(SQL('''
            SELECT r.id,r.recipient_user_id,r.delivered_at,r.read_at
            FROM baseer_bchat_message_receipt r
            JOIN baseer_bchat_membership m ON m.id=r.membership_id
            JOIN baseer_bchat_message msg ON msg.id=r.message_id
            JOIN res_users u ON u.id=r.recipient_user_id
            WHERE r.message_id=%s AND r.id>%s AND %s ORDER BY r.id LIMIT 31
        ''', message.id, after, eligible))
        found = self.env.cr.fetchall()
        names = self._v2_visible_user_names([row[1] for row in found[:PAGE_SIZE]])
        rows = [{'id': receipt_id, 'user_id': recipient_id, 'user_name': names.get(recipient_id, 'User'),
                 'delivered_at': fields.Datetime.to_string(delivered) if delivered else None,
                 'read_at': fields.Datetime.to_string(read) if read else None}
                for receipt_id, recipient_id, delivered, read in found]
        return _bounded_page({'api_version': 2, 'room_id': room.id, 'membership_id': member.id,
                              'message_id': message.id, 'state': summary['state'], 'counts': summary['counts']},
                             'receipts', rows, 'id')
