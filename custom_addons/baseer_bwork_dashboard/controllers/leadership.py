import json

from odoo.addons.baseer_bwork.compatibility import routes, wire_payload, validate_headers, response_header, upload_token

from odoo import fields, http
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.http import request
from odoo.addons.baseer_bwork.contracts import ProtocolError
from odoo.addons.baseer_bwork.controllers.api_v2 import BWorkTextApi

from ..contracts import MAX_RESPONSE_BYTES, parse_query


class LeadershipApi(BWorkTextApi):
    def _leadership_response(self, value):
        if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ProtocolError('response_too_large', 'Dashboard response exceeds 1 MiB.', 413)
        return self._response(value)

    @staticmethod
    def _leadership_no_body():
        if request.httprequest.get_data(cache=True):
            raise ProtocolError('invalid_payload', 'A dashboard GET request cannot have a body.')

    def _leadership_error(self, error):
        if isinstance(error, ValidationError):
            return self._error(ProtocolError('report_unavailable', str(error), 422))
        return self._error(error)

    @http.route(routes('/bwork/api/v2/leadership/options'), type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True, readonly=True, max_content_length=1024)
    def leadership_options(self, **kwargs):
        try:
            self._leadership_no_body()
            self._no_query()
            return self._leadership_response(self._service()._leadership_options())
        except (AccessError, MissingError, ValidationError, ProtocolError) as error:
            return self._leadership_error(error)

    @http.route(routes('/bwork/api/v2/leadership'), type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True, readonly=True, max_content_length=1024)
    def leadership(self, **kwargs):
        try:
            self._leadership_no_body()
            service = self._service()
            as_of = fields.Datetime.to_datetime(fields.Datetime.now())
            today = fields.Date.context_today(service.with_context(tz='Asia/Riyadh'), timestamp=as_of)
            selection = parse_query(request.httprequest.args, today)
            return self._leadership_response(service._leadership(selection, as_of=as_of))
        except (AccessError, MissingError, ValidationError, ProtocolError) as error:
            return self._leadership_error(error)
