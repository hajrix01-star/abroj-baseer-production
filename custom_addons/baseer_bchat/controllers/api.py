from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError, parse_payload


class BChatApi(http.Controller):
    def _response(self, payload, status=200):
        return request.make_json_response(payload, status=status, headers=[
            ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
            ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
        ])

    def _service(self):
        # auth=user invokes native session authentication before this handler.
        # Explicitly reject sudo environments or partially completed MFA.
        if (not request.session.uid or request.env.uid != request.session.uid
                or request.env.su):
            raise AccessError('An individual authenticated session is required.')
        return request.env['baseer.bchat.service']

    def _error(self, error):
        if isinstance(error, ProtocolError):
            return self._response(error.as_payload(), error.status)
        return self._response({'api_version': 1, 'error': {
            'code': 'forbidden', 'message': 'This operation is not permitted.',
        }}, 403)

    @http.route('/bchat/api/v1/bootstrap', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def bootstrap(self, **kwargs):
        try:
            result = self._service()._bootstrap()
            result['csrf_token'] = request.csrf_token()
            return self._response(result)
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v1/messages', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True,
                max_content_length=131072)
    def message(self, payload=None, **kwargs):
        try:
            if kwargs:
                raise ProtocolError('invalid_payload', 'Unexpected form fields.')
            # No business write occurs today. A future implementation MUST wrap
            # operations in a savepoint before catching translated errors here.
            return self._response(self._service()._submit_message(parse_payload(payload)))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v1/conversations', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True,
                max_content_length=131072)
    def conversation(self, payload=None, **kwargs):
        try:
            if kwargs:
                raise ProtocolError('invalid_payload', 'Unexpected form fields.')
            return self._response(self._service()._create_conversation(parse_payload(payload)))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
