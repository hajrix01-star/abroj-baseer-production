"""Same-session BChat media transport; no public attachment URL is returned."""
from urllib.parse import quote

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError, parse_payload
from ..media_contracts import MAX_UPLOAD_LIMIT, size_limit


class BChatMediaApi(http.Controller):
    @staticmethod
    def _service():
        if not request.session.uid or request.env.uid != request.session.uid or request.env.su:
            raise AccessError('An individual authenticated session is required.')
        return request.env['baseer.bchat.service']

    @staticmethod
    def _json(payload, status=200):
        return request.make_json_response(payload, status=status, headers=[
            ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
            ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
        ])

    def _error(self, error):
        if isinstance(error, ProtocolError):
            return self._json({'api_version': 2, 'error': {
                'code': error.code, 'message': str(error),
            }}, error.status)
        return self._json({'api_version': 2, 'error': {
            'code': 'forbidden', 'message': 'This media is unavailable.',
        }}, 403)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/uploads', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True,
                max_content_length=MAX_UPLOAD_LIMIT + 32 * 1024)
    def upload(self, room_id, **kwargs):
        try:
            incoming = request.httprequest
            if incoming.args or incoming.content_type.split(';', 1)[0].strip().lower() != 'multipart/form-data':
                raise ProtocolError('invalid_payload', 'A multipart upload is required.')
            if incoming.content_length is not None and incoming.content_length > MAX_UPLOAD_LIMIT + 32 * 1024:
                raise ProtocolError('payload_too_large', 'The upload is too large.', 413)
            form, files = incoming.form, incoming.files
            if (set(form) != {'csrf_token', 'metadata'} or set(files) != {'file'}
                    or any(len(form.getlist(key)) != 1 for key in form)
                    or len(files.getlist('file')) != 1):
                raise ProtocolError('invalid_payload', 'One metadata object and file are required.')
            if len(form['metadata'].encode('utf-8')) > 4096:
                raise ProtocolError('payload_too_large', 'Upload metadata is too large.', 413)
            metadata = parse_payload(form['metadata'])
            service = self._service()
            normalized = service._v2_upload_scope(room_id, metadata)
            limit = size_limit(normalized['kind'], normalized['mime'])
            raw = files['file'].stream.read(limit + 1)
            if len(raw) > limit:
                raise ProtocolError('payload_too_large', 'The file is too large.', 413)
            return self._json(service._v2_upload(room_id, metadata, raw))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/uploads/<int:media_id>/cancel', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=1024)
    def cancel_upload(self, media_id, **kwargs):
        try:
            incoming = request.httprequest
            if incoming.content_length is not None and incoming.content_length > 1024:
                raise ProtocolError('payload_too_large', 'The request is too large.', 413)
            if (incoming.args
                    or incoming.content_type.split(';', 1)[0].strip().lower()
                    != 'application/x-www-form-urlencoded'
                    or incoming.files or set(incoming.form) != {'csrf_token'}
                    or len(incoming.form.getlist('csrf_token')) != 1):
                raise ProtocolError('invalid_payload', 'Only the CSRF token is accepted.')
            return self._json(self._service()._v2_cancel_upload(media_id))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    def _content(self, media_id, thumbnail):
        try:
            if request.httprequest.args:
                raise ProtocolError('invalid_payload', 'Unexpected query fields.')
            raw, mime, name = self._service()._v2_media_content(media_id, thumbnail)
            disposition = 'inline; filename="bchat-thumbnail.jpg"' if thumbnail else (
                'attachment; filename="bchat-file"; filename*=UTF-8\'\'' + quote(name, safe=''))
            return request.make_response(raw, status=200, headers=[
                ('Content-Type', mime), ('Content-Length', str(len(raw))),
                ('Content-Disposition', disposition),
                ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
                ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
                ('Content-Security-Policy', "default-src 'none'; sandbox"),
            ])
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/media/<int:media_id>/content', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def content(self, media_id, **kwargs):
        return self._content(media_id, False)

    @http.route('/bchat/api/v2/media/<int:media_id>/thumbnail', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def thumbnail(self, media_id, **kwargs):
        return self._content(media_id, True)
