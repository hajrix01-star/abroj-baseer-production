import re

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.addons.baseer_bchat.contracts import ProtocolError
from odoo.addons.baseer_bchat.controllers.api_v2 import BChatTextApi


class BChatMobilePolicyApi(BChatTextApi):
    @http.route('/bchat/api/v2/mobile/candidates', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def mobile_candidates(self, **kwargs):
        try:
            args = request.httprequest.args
            if (set(args) - {'company_id', 'q'} or 'company_id' not in args
                    or any(len(args.getlist(key)) != 1 for key in args)
                    or not re.fullmatch(r'[1-9][0-9]*', args['company_id'])):
                raise ProtocolError('invalid_payload', 'Invalid member search fields.')
            return self._response(self._service()._mobile_candidates(
                int(args['company_id']), args.get('q', '')))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/mobile/policy', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def mobile_policy(self, **kwargs):
        try:
            args = request.httprequest.args
            if (set(args) != {'company_id'} or len(args.getlist('company_id')) != 1
                    or not re.fullmatch(r'[1-9][0-9]*', args['company_id'])):
                raise ProtocolError('invalid_payload', 'Exactly one positive company_id is required.')
            return self._response(self._service()._mobile_policy(int(args['company_id'])))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/mobile/policy', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def mobile_policy_set(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._mobile_policy_set(self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/mobile/direct', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def mobile_direct(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._mobile_direct(self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
