"""Session and CSRF-bound BChat order endpoints; no generic procurement RPC."""
import base64
import re

from odoo import http
from odoo.exceptions import AccessError, ConcurrencyError, UserError, ValidationError
from odoo.http import request

from odoo.addons.baseer_bchat.contracts import ProtocolError, parse_payload


class BChatOrderApi(http.Controller):
    @staticmethod
    def _response(payload, status=200):
        return request.make_json_response(payload, status=status, headers=[
            ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
            ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
        ])

    def _error(self, error):
        if isinstance(error, ProtocolError):
            return self._response({'api_version': 2, 'error': {
                'code': error.code, 'message': str(error),
            }}, error.status)
        if isinstance(error, ConcurrencyError):
            return self._response({'api_version': 2, 'error': {
                'code': 'retry', 'message': 'The request is being submitted; retry with the same UUID.',
            }}, 409)
        if isinstance(error, AccessError):
            return self._response({'api_version': 2, 'error': {
                'code': 'forbidden', 'message': 'This operation is not permitted.',
            }}, 403)
        if isinstance(error, (ValidationError, UserError)):
            return self._response({'api_version': 2, 'error': {
                'code': 'invalid_order', 'message': 'The order could not be submitted with these details.',
            }}, 400)
        return self._response({'api_version': 2, 'error': {
            'code': 'forbidden', 'message': 'This operation is not permitted.',
        }}, 403)

    @staticmethod
    def _service():
        if not request.session.uid or request.env.uid != request.session.uid or request.env.su:
            raise AccessError('An individual authenticated session is required.')
        return request.env['baseer.bchat.service']

    @staticmethod
    def _id(raw, field):
        if not isinstance(raw, str) or not re.fullmatch(r'[1-9][0-9]*', raw):
            raise ProtocolError('invalid_payload', '%s must be a positive record ID.' % field)
        value = int(raw)
        if value > 2147483647:
            raise ProtocolError('invalid_payload', '%s is outside the record ID limit.' % field)
        return value

    @staticmethod
    def _args(allowed):
        args = request.httprequest.args
        if set(args) - set(allowed) or any(len(args.getlist(key)) != 1 for key in args):
            raise ProtocolError('invalid_payload', 'Unexpected or repeated query fields.')
        return args

    @staticmethod
    def _form():
        http_request = request.httprequest
        if http_request.content_type.split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
            raise ProtocolError('invalid_payload', 'A form payload is required.')
        if http_request.content_length is not None and http_request.content_length > 65536:
            raise ProtocolError('payload_too_large', 'Request exceeds 64 KiB.', 413)
        form = http_request.form
        if set(form) != {'csrf_token', 'payload'} or any(len(form.getlist(key)) != 1 for key in form):
            raise ProtocolError('invalid_payload', 'Exactly one CSRF token and payload are required.')
        return parse_payload(form['payload'])

    @http.route('/bchat/api/v2/orders/options', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def options(self, **kwargs):
        try:
            args = self._args(('company_id',))
            company_id = self._id(args['company_id'], 'company_id') if 'company_id' in args else None
            return self._response(self._service()._v2_order_options(company_id))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/orders/catalog', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def catalog(self, **kwargs):
        try:
            if self._form() != {'api_version': 2}:
                raise ProtocolError('invalid_payload', 'Catalogue request version is invalid.')
            args = self._args(('company_id', 'q', 'category_id', 'after_id'))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            company_id = self._id(args['company_id'], 'company_id')
            category_id = self._id(args['category_id'], 'category_id') if 'category_id' in args else None
            after_id = self._id(args['after_id'], 'after_id') if 'after_id' in args else None
            return self._response(self._service()._v2_order_catalog(
                company_id, args.get('q'), category_id, after_id,
            ))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/orders/catalog/resolve', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def catalog_resolve(self, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._v2_order_catalog_resolve(self._form()))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/orders', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def orders(self, **kwargs):
        try:
            args = self._args(('company_id', 'before_id', 'scope'))
            before_id = self._id(args['before_id'], 'before_id') if 'before_id' in args else None
            if 'scope' in args:
                if args['scope'] != 'all' or 'company_id' in args:
                    raise ProtocolError('invalid_payload', 'Choose one supported order scope.')
                return self._response(self._service()._v2_orders_all(before_id))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            company_id = self._id(args['company_id'], 'company_id')
            return self._response(self._service()._v2_orders(company_id, before_id))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/orders/<int:order_id>', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def order_detail(self, order_id, **kwargs):
        try:
            args = self._args(('company_id', 'scope'))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            if 'scope' in args and args['scope'] != 'all':
                raise ProtocolError('invalid_payload', 'Unknown order scope.')
            company_id = self._id(args['company_id'], 'company_id')
            return self._response(self._service()._v2_order_detail(
                company_id, order_id, scope=args.get('scope'),
            ))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/orders', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def create(self, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._v2_order_create(self._form()))
        except (AccessError, ProtocolError, ConcurrencyError, ValidationError, UserError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/orders/quote', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def quote(self, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._v2_order_quote(self._form()))
        except (AccessError, ProtocolError, ValidationError, UserError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/orders/image/<int:product_id>', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def image(self, product_id, **kwargs):
        try:
            args = self._args(('company_id',))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            encoded = self._service()._v2_order_image(self._id(args['company_id'], 'company_id'), product_id)
            binary = base64.b64decode(encoded, validate=True)
            if not binary or len(binary) > 131072:
                raise ProtocolError('invalid_image', 'The thumbnail is unavailable.', 404)
            if binary.startswith(b'\xff\xd8'):
                mime = 'image/jpeg'
            elif binary.startswith(b'\x89PNG\r\n\x1a\n'):
                mime = 'image/png'
            elif binary.startswith(b'RIFF') and binary[8:12] == b'WEBP':
                mime = 'image/webp'
            else:
                raise ProtocolError('invalid_image', 'The thumbnail is unavailable.', 404)
            return request.make_response(binary, headers=[
                ('Content-Type', mime), ('Cache-Control', 'private, no-store'),
                ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
            ])
        except (AccessError, ProtocolError, ValueError) as error:
            return self._error(error)
