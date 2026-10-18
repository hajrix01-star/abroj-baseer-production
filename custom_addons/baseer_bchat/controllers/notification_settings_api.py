"""Narrow settings/self-test endpoints; no recipient or business-message writes."""
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError
from .api_v2 import BChatTextApi


class BChatNotificationSettingsApi(http.Controller):
    _response = BChatTextApi._response
    _service = BChatTextApi._service
    _group_form_payload = BChatTextApi._group_form_payload
    _no_query = staticmethod(BChatTextApi._no_query)

    def _error(self, error):
        if isinstance(error, ProtocolError):
            data = {'code': error.code, 'message': str(error)}
            if error.code == 'rate_limited':
                data['retry_after_seconds'] = error.retry_after_seconds
            return self._response({'api_version': 2, 'error': data}, error.status)
        return BChatTextApi._error(self, error)

    def _installation_arg(self):
        args = request.httprequest.args
        if set(args) != {'installation_id'} or len(args.getlist('installation_id')) != 1:
            raise ProtocolError('invalid_payload', 'Exactly one installation ID is required.')
        return args['installation_id']

    @http.route('/bchat/api/v2/notifications/preferences', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def preferences(self, **kwargs):
        try:
            return self._response(self._service()._v2_notification_preferences(self._installation_arg()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/notifications/preferences', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def set_preferences(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_notification_set_preferences(self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/notifications/test', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def test(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_notification_test(self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/notifications/test/<int:event_id>', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def test_status(self, event_id, **kwargs):
        try:
            return self._response(self._service()._v2_notification_test_status(self._installation_arg(), event_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
