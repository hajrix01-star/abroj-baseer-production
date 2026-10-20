"""Read-only scoped reconciliation over authenticated, CSRF-bound POST."""
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError
from .api_v2 import BChatTextApi


class BChatRetentionApi(BChatTextApi):
    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages/<int:message_id>/preserve',
                type='http', auth='user', methods=['POST'], csrf=True,
                save_session=True, max_content_length=65536)
    def preserve(self, room_id, message_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_preserve_message(room_id, message_id, self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/content-state', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def content_state(self, room_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_content_state(room_id, self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            if isinstance(error, ProtocolError) and error.code == 'content_changed':
                return self._response({'api_version': 2, 'content_revision': error.content_revision,
                    'error': {'code': error.code, 'message': str(error)}}, error.status)
            return self._error(error)
