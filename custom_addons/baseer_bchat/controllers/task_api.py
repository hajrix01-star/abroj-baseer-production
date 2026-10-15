"""Bounded same-origin BChat v2 task routes; never generic model RPC."""
import re

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError, parse_payload


class BChatTaskApi(http.Controller):
    def _response(self, payload, status=200):
        return request.make_json_response(payload, status=status, headers=[
            ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
            ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
        ])

    def _error(self, error):
        if isinstance(error, ProtocolError):
            return self._response({'api_version': 2, 'error': {
                'code': error.code, 'message': str(error),
            }}, error.status)
        return self._response({'api_version': 2, 'error': {
            'code': 'forbidden', 'message': 'This operation is not permitted.',
        }}, 403)

    def _service(self):
        if (not request.session.uid or request.env.uid != request.session.uid
                or request.env.su):
            raise AccessError('An individual authenticated session is required.')
        return request.env['baseer.bchat.service']

    @staticmethod
    def _id(raw, name):
        if not isinstance(raw, str) or not re.fullmatch(r'[1-9][0-9]*', raw):
            raise ProtocolError('invalid_payload', '%s must be a positive record ID.' % name)
        value = int(raw)
        if value > 2147483647:
            raise ProtocolError('invalid_payload', '%s is outside the record ID limit.' % name)
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

    @http.route('/bchat/api/v2/tasks/options', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def options(self, **kwargs):
        try:
            args = self._args(('company_id', 'room_id'))
            company_id = self._id(args['company_id'], 'company_id') if 'company_id' in args else None
            room_id = self._id(args['room_id'], 'room_id') if 'room_id' in args else None
            return self._response(self._service()._v2_task_options(company_id, room_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/tasks', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def tasks(self, **kwargs):
        try:
            args = self._args(('before_id', 'room_id', 'state'))
            before_id = self._id(args['before_id'], 'before_id') if 'before_id' in args else None
            room_id = self._id(args['room_id'], 'room_id') if 'room_id' in args else None
            state = args.get('state')
            return self._response(self._service()._v2_tasks(before_id, room_id, state))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/tasks/<int:task_id>', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def detail(self, task_id, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._v2_task_detail(task_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/tasks', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def create(self, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._v2_task_create(self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/tasks/<int:task_id>/transition', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def transition(self, task_id, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._v2_task_transition(task_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
