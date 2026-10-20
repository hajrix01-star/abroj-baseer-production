"""Read-only sparse gallery. Never commits history coverage or read receipts."""
from odoo import api, models
from odoo.tools import SQL

from .. import gallery_contracts as wire


class BWorkGalleryService(models.AbstractModel):
    _inherit = 'baseer.bwork.service'

    @api.model
    def _v2_bootstrap(self):
        result = super()._v2_bootstrap()
        result['capabilities']['media_gallery_version'] = 1
        return result

    @api.model
    def _v2_gallery(self, room_id, kind='all', order='newest', limit=wire.DEFAULT_PAGE, cursor=None, q=''):
        self._require_bwork_permission('chat_view')
        self._require_bwork_permission('media')
        kind, order, limit = wire.options(kind, order, limit)
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        q = wire.search(q)
        after = wire.anchor(cursor, room.id, member.id, kind, order, room.content_revision, q)
        self.env['baseer.bwork.message'].flush_model()
        self.env['baseer.bwork.media'].flush_model()
        keyset = SQL('')
        if after:
            message, size = after
            if order == 'largest':
                keyset = SQL('AND (media.size_bytes, message.id) < (%s, %s)', size, message)
            elif order == 'oldest':
                keyset = SQL('AND message.id > %s', message)
            else:
                keyset = SQL('AND message.id < %s', message)
        sorting = {'largest': SQL('media.size_bytes DESC, message.id DESC'),
                   'oldest': SQL('message.id ASC'), 'newest': SQL('message.id DESC')}[order]
        # All invariants precede metadata reads, including the inverse link and
        # current member's message visibility floor. Admin rights do not enter.
        self.env.cr.execute(SQL('''
            SELECT message.id, media.size_bytes
            FROM baseer_bwork_message message
            JOIN baseer_bwork_media media ON media.id = message.media_id
                AND media.message_id = message.id AND media.state = 'attached'
                AND media.room_id = message.room_id AND media.company_id = message.company_id
                AND media.retention_state = 'active'
            WHERE message.room_id = %s AND message.company_id = %s
              AND message.id > %s AND (%s = 'all' OR media.kind = %s)
              AND message.retention_state = 'active' AND media.name ILIKE %s
              %s ORDER BY %s LIMIT %s
        ''', room.id, room.company_id.id, member.joined_after_message_id,
            kind, kind, wire.search_pattern(q), keyset, sorting, limit + 1))
        found = self.env.cr.fetchall()
        page = self.env['baseer.bwork.message'].sudo().browse([row[0] for row in found[:limit]])
        parent_ids = page.mapped('reply_to_message_id').ids
        parents = self.env['baseer.bwork.message'].sudo().search([
            ('id', 'in', parent_ids), ('room_id', '=', room.id),
            ('company_id', '=', room.company_id.id), ('id', '>', member.joined_after_message_id),
        ]) if parent_ids else self.env['baseer.bwork.message']
        names = self._v2_author_names(list(page) + list(parents))
        # Serializer reverses its input to chronological history order; reverse
        # here to preserve the explicitly selected gallery order, not history.
        rows = self._v2_history_payload(list(reversed(page)), False, names,
                                       {row.id: row for row in parents})['messages']
        for row in rows:
            row['media']['size_label'] = wire.size_label(row['media']['size'])
        return wire.response(room.id, room.company_id.id, member.id, kind, order,
                             rows, len(found) > len(rows), room.content_revision, q)
