"""C13 session-bound read routes; the existing POST ACK contract is unchanged."""
import re

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError
from .api_v2 import BChatTextApi


class BChatReceiptDeliveryApi(http.Controller):
    _response = BChatTextApi._response
    _service = BChatTextApi._service
    _error = BChatTextApi._error

    @staticmethod
    def _after():
        args = request.httprequest.args
        if set(args) - {'after_id'} or any(len(args.getlist(key)) != 1 for key in args):
            raise ProtocolError('invalid_payload', 'Unexpected or repeated receipt query fields.')
        value = args.get('after_id', '0')
        if not re.fullmatch(r'0|[1-9][0-9]{0,9}', value) or int(value) > 2147483647:
            raise ProtocolError('invalid_payload', 'A nonnegative receipt cursor is required.')
        return int(value)

    @http.route('/bchat/api/v2/receipts/pending', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def pending(self, **kwargs):
        try:
            return self._response(self._service()._v2_pending_receipts(self._after()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages/<int:message_id>/receipts',
                type='http', auth='user', methods=['GET'], csrf=True, save_session=True)
    def details(self, room_id, message_id, **kwargs):
        try:
            return self._response(self._service()._v2_receipt_details(room_id, message_id, self._after()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
