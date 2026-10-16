"""Session-bound, no-CORS BChat-only text endpoints."""
import re

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError, parse_payload


class BChatTextApi(http.Controller):
    def _response(self, payload, status=200):
        return request.make_json_response(payload, status=status, headers=[
            ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
            ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
        ])

    def _service(self):
        if (not request.session.uid or request.env.uid != request.session.uid
                or request.env.su):
            raise AccessError('An individual authenticated session is required.')
        return request.env['baseer.bchat.service']

    def _error(self, error):
        if isinstance(error, ProtocolError):
            return self._response({'api_version': 2, 'error': {
                'code': error.code, 'message': str(error),
            }}, error.status)
        return self._response({'api_version': 2, 'error': {
            'code': 'forbidden', 'message': 'This operation is not permitted.',
        }}, 403)

    @staticmethod
    def _no_query():
        if request.httprequest.args:
            raise ProtocolError('invalid_payload', 'Unexpected query fields.')

    @http.route('/bchat/api/v2/bootstrap', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def bootstrap(self, **kwargs):
        try:
            self._no_query()
            result = self._service()._v2_bootstrap()
            result['csrf_token'] = request.csrf_token()
            return self._response(result)
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def rooms(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_rooms())
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/attention', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def attention(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_attention())
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    def _group_form_payload(self):
        incoming = request.httprequest
        if incoming.content_type.split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
            raise ProtocolError('invalid_payload', 'A form payload is required.')
        if incoming.content_length is not None and incoming.content_length > 65536:
            raise ProtocolError('payload_too_large', 'Request exceeds 64 KiB.', 413)
        form = incoming.form
        if set(form) != {'csrf_token', 'payload'} or any(len(form.getlist(key)) != 1 for key in form):
            raise ProtocolError('invalid_payload', 'Exactly one CSRF token and payload are required.')
        return parse_payload(form['payload'])

    @http.route('/bchat/api/v2/rooms', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def create_group(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_group_create(self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/member-candidates', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def member_candidates(self, **kwargs):
        try:
            args = request.httprequest.args
            if (set(args) - {'company_id', 'q'} or 'company_id' not in args
                    or any(len(args.getlist(key)) != 1 for key in args)):
                raise ProtocolError('invalid_payload', 'Invalid member search fields.')
            raw = args['company_id']
            if not re.fullmatch(r'[1-9][0-9]*', raw):
                raise ProtocolError('invalid_payload', 'Invalid company ID.')
            return self._response(self._service()._v2_group_member_candidates(int(raw), args.get('q', '')))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/group', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def group_detail(self, room_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_group_detail(room_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/group', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def group_change(self, room_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_group_change(room_id, self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/avatar', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def group_avatar(self, room_id, **kwargs):
        try:
            args = request.httprequest.args
            if set(args) - {'version'} or any(len(args.getlist(key)) != 1 for key in args):
                raise ProtocolError('invalid_payload', 'Invalid group image query.')
            if 'version' in args and not re.fullmatch(r'(?:0|[1-9][0-9]*)', args['version']):
                raise ProtocolError('invalid_payload', 'Invalid group image version.')
            raw, version = self._service()._v2_group_avatar(room_id)
            return request.make_response(raw, headers=[
                ('Content-Type', 'image/png'), ('Cache-Control', 'no-store'),
                ('Pragma', 'no-cache'), ('Vary', 'Cookie'),
                ('X-Content-Type-Options', 'nosniff'),
                ('X-BChat-Avatar-Version', str(version)),
            ])
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/avatar', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True,
                max_content_length=2 * 1024 * 1024 + 65536)
    def group_avatar_upload(self, room_id, **kwargs):
        try:
            self._no_query()
            incoming = request.httprequest
            if incoming.content_type.split(';', 1)[0].strip().lower() != 'multipart/form-data':
                raise ProtocolError('invalid_payload', 'A multipart image is required.')
            if (set(incoming.form) != {'csrf_token'} or len(incoming.form.getlist('csrf_token')) != 1
                    or set(incoming.files) != {'file'} or len(incoming.files.getlist('file')) != 1):
                raise ProtocolError('invalid_payload', 'Exactly one image is required.')
            raw = incoming.files['file'].stream.read(2 * 1024 * 1024 + 1)
            return self._response(self._service()._v2_group_set_avatar(room_id, raw))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/changes', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def changes(self, **kwargs):
        try:
            args = request.httprequest.args
            if (set(args) - {'after', 'limit', 'permissions_version'}
                    or any(len(args.getlist(key)) != 1 for key in args)
                    or (args.get('permissions_version') not in (None, '1'))):
                raise ProtocolError('invalid_payload', 'Unexpected or repeated query fields.')
            after_raw = args.get('after', '0')
            limit_raw = args.get('limit', '100')
            if (not re.fullmatch(r'(?:0|[1-9][0-9]*)', after_raw)
                    or not re.fullmatch(r'[1-9][0-9]*', limit_raw)):
                raise ProtocolError('invalid_payload', 'Invalid change cursor or limit.')
            return self._response(self._service()._v2_changes(
                int(after_raw), int(limit_raw),
                include_permissions=args.get('permissions_version') == '1',
            ))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/changes/snapshot', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def changes_snapshot(self, **kwargs):
        try:
            args = request.httprequest.args
            if (set(args) - {'section', 'before_id', 'watermark'}
                    or any(len(args.getlist(key)) != 1 for key in args)
                    or 'section' not in args or 'watermark' not in args):
                raise ProtocolError('invalid_payload', 'Invalid snapshot query fields.')
            before_raw = args.get('before_id')
            watermark_raw = args['watermark']
            if ((before_raw is not None and not re.fullmatch(r'[1-9][0-9]*', before_raw))
                    or not re.fullmatch(r'(?:0|[1-9][0-9]*)', watermark_raw)):
                raise ProtocolError('invalid_payload', 'Invalid snapshot cursor.')
            return self._response(self._service()._v2_change_snapshot(
                args['section'], int(before_raw) if before_raw else None,
                int(watermark_raw),
            ))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/notifications/register', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def notification_register(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_push_register(self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/notifications/unregister', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=1024)
    def notification_unregister(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_push_unregister(self._group_form_payload()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/notifications/<int:event_id>', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def notification_event(self, event_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_push_event(event_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def history(self, room_id, **kwargs):
        try:
            args = request.httprequest.args
            if set(args) - {'before_id'} or len(args.getlist('before_id')) > 1:
                raise ProtocolError('invalid_payload', 'Unexpected or repeated query fields.')
            before_raw = args.get('before_id')
            if before_raw is not None and not re.fullmatch(r'[1-9][0-9]*', before_raw):
                raise ProtocolError('invalid_payload', 'before_id must be a positive record ID.')
            before_id = int(before_raw) if before_raw is not None else None
            return self._response(self._service()._v2_history(room_id, before_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True,
                max_content_length=65536)
    def send(self, room_id, **kwargs):
        try:
            self._no_query()
            http_request = request.httprequest
            if http_request.content_type.split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
                raise ProtocolError('invalid_payload', 'A form payload is required.')
            if (http_request.content_length is not None
                    and http_request.content_length > 65536):
                raise ProtocolError('payload_too_large', 'Request exceeds 64 KiB.', 413)
            form = http_request.form
            if set(form) != {'csrf_token', 'payload'} or any(len(form.getlist(key)) != 1 for key in form):
                raise ProtocolError('invalid_payload', 'Exactly one CSRF token and payload are required.')
            return self._response(self._service()._v2_send(room_id, parse_payload(form['payload'])))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages/<int:message_id>',
                type='http', auth='user', methods=['GET'], csrf=True, save_session=True)
    def message(self, room_id, message_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_message(room_id, message_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/messages/<int:message_id>/receipts',
                type='http', auth='user', methods=['POST'], csrf=True,
                save_session=True, max_content_length=1024)
    def receipt_ack(self, room_id, message_id, **kwargs):
        try:
            self._no_query()
            incoming = request.httprequest
            if incoming.content_type.split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
                raise ProtocolError('invalid_payload', 'A form payload is required.')
            if incoming.content_length is not None and incoming.content_length > 1024:
                raise ProtocolError('payload_too_large', 'Receipt request is too large.', 413)
            form = incoming.form
            if set(form) != {'csrf_token', 'kind'} or any(len(form.getlist(key)) != 1 for key in form):
                raise ProtocolError('invalid_payload', 'A CSRF token and receipt kind are required.')
            return self._response(self._service()._v2_receipt_ack(room_id, message_id, form['kind']))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
