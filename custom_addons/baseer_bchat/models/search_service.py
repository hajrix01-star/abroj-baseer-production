"""Indexed, room/epoch-bound lexical search; no query in a URL or audit body."""
import json
import unicodedata

from odoo import api, models

from ..contracts import ProtocolError, positive_id


class BChatSearchMessageIndex(models.Model):
    _inherit = 'baseer.bchat.message'

    def init(self):
        super().init()
        self.env.cr.execute('''CREATE INDEX IF NOT EXISTS baseer_bchat_message_text_search_idx
            ON baseer_bchat_message USING gin (to_tsvector('simple'::regconfig, COALESCE(text,'')))''')


class BChatSearchMediaIndex(models.Model):
    _inherit = 'baseer.bchat.media'

    def init(self):
        super().init()
        self.env.cr.execute('''CREATE INDEX IF NOT EXISTS baseer_bchat_media_name_search_idx
            ON baseer_bchat_media USING gin (to_tsvector('simple'::regconfig,
                regexp_replace(COALESCE(name,''),'[._/-]+',' ','g')))
            WHERE state = 'attached' AND message_id IS NOT NULL''')
        self.env.cr.execute('''CREATE INDEX IF NOT EXISTS baseer_bchat_media_gallery_idx
            ON baseer_bchat_media (room_id,kind,message_id DESC)
            WHERE state = 'attached' AND message_id IS NOT NULL''')


class BChatSearchService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _search_room_scope(self, room_id, membership_id, kind, *, gallery=False):
        user = self._require_bchat_permission('chat_view')
        if kind not in ('all', 'text', 'image', 'file', 'audio') or (gallery and kind == 'text'):
            raise ProtocolError('invalid_payload', 'Choose a supported message filter.')
        if gallery or kind in ('image', 'file', 'audio'):
            self._require_media_right('view')
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        if member.id != positive_id(membership_id, 'membership_id'):
            raise ProtocolError('membership_changed', 'The membership period changed.', 409)
        return room, member, bool(user._bchat_effective_permissions()['media_view'])

    @api.model
    def _search_payload(self, room, member, ids):
        found = self.env['baseer.bchat.message'].sudo().browse(ids).exists()
        page = list(found[:30])
        more = len(found) > 30
        reply_ids = [row.reply_to_message_id.id for row in page if row.reply_to_message_id]
        parents = self.env['baseer.bchat.message'].sudo().search([
            ('id', 'in', reply_ids), ('room_id', '=', room.id), ('company_id', '=', room.company_id.id),
            ('id', '>', member.joined_after_message_id),
        ], limit=30) if reply_ids else self.env['baseer.bchat.message']
        parent_by_id = {row.id: row for row in parents}
        authors = self._v2_author_names(page + list(parents))
        while True:
            result = self._v2_history_payload(page, more, authors, parent_by_id)
            result['membership_id'] = member.id
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) <= 131072:
                return result
            if len(page) <= 1:
                raise ProtocolError('page_too_large', 'Search page exceeds its supported size.', 413)
            page.pop()
            more = True

    @api.model
    def _v2_room_search(self, room_id, payload):
        if (type(payload) is not dict or set(payload) != {'api_version', 'membership_id', 'q', 'kind', 'before_id'}
                or type(payload['api_version']) is not int or payload['api_version'] != 2):
            raise ProtocolError('invalid_payload', 'Invalid read-only search fields.')
        query = payload['q']
        try:
            size = len(query.encode('utf-8')) if type(query) is str else 0
        except UnicodeError:
            raise ProtocolError('invalid_payload', 'Search text must be UTF-8.') from None
        if (type(query) is not str or not query.strip() or size > 128 or len(query.split()) > 8
                or any(unicodedata.category(char).startswith('C') for char in query)):
            raise ProtocolError('invalid_payload', 'Use a short search of at most eight words.')
        kind = payload['kind']
        if type(kind) is not str:
            raise ProtocolError('invalid_payload', 'Choose a supported message filter.')
        before = payload['before_id']
        if before is not None:
            before = positive_id(before, 'before_id')
        room, member, media_view = self._search_room_scope(room_id, payload['membership_id'], kind)
        visible = 'm.room_id = %s AND m.company_id = %s AND m.id > %s'
        parameters = [room.id, room.company_id.id, member.joined_after_message_id]
        if before is not None:
            visible += ' AND m.id < %s'
            parameters.append(before)
        media_join = '''JOIN baseer_bchat_media AS media ON media.id = m.media_id
            AND media.message_id = m.id AND media.room_id = m.room_id
            AND media.company_id = m.company_id AND media.state = 'attached' '''
        kind_filter, kind_parameters = '', []
        if kind == 'text':
            kind_filter = ' AND m.media_id IS NULL'
        elif kind != 'all':
            kind_filter, kind_parameters = ' AND media.kind = %s', [kind]
        # Each branch has its own indexable expression; no cross-table OR
        # which would make the filename search depend on scanning chat text.
        text_join = media_join if kind not in ('all', 'text') else ''
        clauses = ['(SELECT m.id FROM baseer_bchat_message AS m ' + text_join +
                   ' WHERE ' + visible + kind_filter +
                   " AND to_tsvector('simple'::regconfig,COALESCE(m.text,'')) @@ plainto_tsquery('simple'::regconfig,%s) "
                   'ORDER BY m.id DESC LIMIT 31)']
        bound = parameters + kind_parameters + [query]
        if media_view and kind != 'text':
            clauses.append('(SELECT m.id FROM baseer_bchat_media AS media JOIN baseer_bchat_message AS m '
                           "ON m.media_id = media.id AND media.message_id = m.id AND media.room_id = m.room_id "
                           "AND media.company_id = m.company_id WHERE media.state = 'attached' AND media.message_id IS NOT NULL AND " + visible + kind_filter +
                           " AND to_tsvector('simple'::regconfig,regexp_replace(COALESCE(media.name,''),'[._/-]+',' ','g')) "
                           "@@ plainto_tsquery('simple'::regconfig,regexp_replace(%s,'[._/-]+',' ','g')) "
                           'ORDER BY m.id DESC LIMIT 31)')
            bound += parameters + kind_parameters + [query]
        self.env.cr.execute('SELECT id FROM (' + ' UNION '.join(clauses) + ') AS hits ORDER BY id DESC LIMIT 31', bound)
        return self._search_payload(room, member, [row[0] for row in self.env.cr.fetchall()])

    @api.model
    def _v2_room_media(self, room_id, membership_id, kind='all', before_id=None):
        if type(kind) is not str:
            raise ProtocolError('invalid_payload', 'Choose a supported media filter.')
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        room, member, _view = self._search_room_scope(room_id, membership_id, kind, gallery=True)
        query = '''SELECT m.id FROM baseer_bchat_message AS m
            JOIN baseer_bchat_media AS media ON media.id = m.media_id
             AND media.message_id = m.id AND media.room_id = m.room_id AND media.company_id = m.company_id
            WHERE m.room_id = %s AND m.company_id = %s AND m.id > %s AND media.state = 'attached'
             AND media.message_id IS NOT NULL '''
        bound = [room.id, room.company_id.id, member.joined_after_message_id]
        if kind != 'all':
            query += ' AND media.kind = %s'
            bound.append(kind)
        if before_id is not None:
            query += ' AND m.id < %s'
            bound.append(before_id)
        self.env.cr.execute(query + ' ORDER BY m.id DESC LIMIT 31', bound)
        return self._search_payload(room, member, [row[0] for row in self.env.cr.fetchall()])
