"""CSRF-bound, role-gated BWork receipt endpoints."""
from odoo.addons.baseer_bwork.compatibility import routes, wire_payload, validate_headers, response_header, upload_token

from odoo import http
from odoo.exceptions import AccessError, ConcurrencyError, UserError, ValidationError

from odoo.addons.baseer_bwork.contracts import ProtocolError

from .orders import BWorkOrderApi


class BWorkReceiptApi(http.Controller):
    @http.route(routes('/bwork/api/v2/orders/receipts'), type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def receipts(self, **kwargs):
        api = BWorkOrderApi()
        try:
            args = api._args(('company_id', 'before_id', 'scope'))
            before_id = api._id(args['before_id'], 'before_id') if 'before_id' in args else None
            if 'scope' in args:
                if args['scope'] != 'all':
                    raise ProtocolError('invalid_payload', 'Choose one supported receipt scope.')
                company_id = api._id(args['company_id'], 'company_id') if 'company_id' in args else None
                return api._response(api._service()._v2_receipts_all(before_id, company_id=company_id))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            company_id = api._id(args['company_id'], 'company_id')
            return api._response(api._service()._v2_receipts(company_id, before_id))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return api._error(error)

    @http.route(routes('/bwork/api/v2/orders/receipts/<int:order_id>'), type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def detail(self, order_id, **kwargs):
        api = BWorkOrderApi()
        try:
            args = api._args(('company_id',))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            company_id = api._id(args['company_id'], 'company_id')
            return api._response(api._service()._v2_receipt_detail(company_id, order_id))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return api._error(error)

    @http.route(routes('/bwork/api/v2/orders/receipts/<int:order_id>/confirm'), type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def confirm(self, order_id, **kwargs):
        api = BWorkOrderApi()
        try:
            api._args(())
            return api._response(api._service()._v2_receipt_confirm(order_id, api._form()))
        except (AccessError, ProtocolError, ConcurrencyError, ValidationError, UserError) as error:
            return api._error(error)

    @http.route(routes('/bwork/api/v2/orders/receipts/<int:order_id>/share'), type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def share(self, order_id, **kwargs):
        api = BWorkOrderApi()
        try:
            api._args(())
            return api._response(api._service()._v2_receipt_share(order_id, api._form()))
        except (AccessError, ProtocolError, ConcurrencyError, ValidationError, UserError) as error:
            return api._error(error)
