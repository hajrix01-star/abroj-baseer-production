"""Additive, same-session gallery transport. No write endpoint or content ACL."""
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError
from ..gallery_contracts import query
from .api_v2 import BChatTextApi


class BChatGalleryApi(BChatTextApi):
    @http.route('/bchat/api/v2/rooms/<int:room_id>/media', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def gallery(self, room_id, **kwargs):
        try:
            return self._response(self._service()._v2_gallery(room_id, **query(request.httprequest.args)))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
