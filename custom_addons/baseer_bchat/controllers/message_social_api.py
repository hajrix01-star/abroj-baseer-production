"""C32 additive routes; no edit/delete endpoint and no legacy response changes."""
from odoo import http
from odoo.exceptions import AccessError

from ..contracts import ProtocolError
from .social_api import BChatSocialApi


class BChatMessageSocialApi(http.Controller):
    _response = BChatSocialApi._response
    _service = BChatSocialApi._service
    _error = BChatSocialApi._error
    _form = BChatSocialApi._form
    _no_query = staticmethod(BChatSocialApi._no_query)
    _args = staticmethod(BChatSocialApi._args)
    _id = staticmethod(BChatSocialApi._id)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages/<int:message_id>/reaction',
                type='http', auth='user', methods=['POST'], csrf=True,
                save_session=True, max_content_length=8192)
    def reaction(self, room_id, message_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_message_reaction(room_id, message_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages/<int:message_id>/saved',
                type='http', auth='user', methods=['POST'], csrf=True,
                save_session=True, max_content_length=8192)
    def saved(self, room_id, message_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_message_saved(room_id, message_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/social-metadata', type='http',
                auth='user', methods=['GET'], csrf=True, save_session=True)
    def metadata(self, room_id, **kwargs):
        try:
            args = self._args(('membership_id', 'message_ids'), ('membership_id', 'message_ids'))
            raw = args['message_ids'].split(',')
            if not 1 <= len(raw) <= 30:
                raise ProtocolError('invalid_payload', 'Choose at most thirty message references.')
            ids = [self._id(value, 'message_id') for value in raw]
            return self._response(self._service()._v2_social_metadata(
                room_id, self._id(args['membership_id'], 'membership_id'), ids))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/social/saved', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def saved_messages(self, **kwargs):
        try:
            args = self._args(('before_id',))
            before = self._id(args['before_id'], 'before_id') if 'before_id' in args else None
            return self._response(self._service()._v2_saved_messages(before))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/social/messages', type='http',
                auth='user', methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def send(self, room_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_social_send(room_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
