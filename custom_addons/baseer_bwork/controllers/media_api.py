"""Same-session BWork media transport; no public attachment URL is returned."""
from urllib.parse import quote

from psycopg2.extensions import TransactionRollbackError
from werkzeug.exceptions import ClientDisconnected

from odoo.addons.baseer_bwork.compatibility import routes, wire_payload, validate_headers, response_header, upload_token

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError, parse_payload
from ..media_contracts import MAX_UPLOAD_LIMIT, size_limit


class BWorkMediaApi(http.Controller):
    @staticmethod
    def _service():
        if not request.session.uid or request.env.uid != request.session.uid or request.env.su:
            raise AccessError('An individual authenticated session is required.')
        try:
            validate_headers(request.httprequest.headers)
        except ValueError:
            raise ProtocolError('invalid_payload', 'Conflicting compatibility headers.')
        return request.env['baseer.bwork.service']

    @staticmethod
    def _json(payload, status=200):
        return request.make_json_response(wire_payload(payload, request.httprequest.path), status=status, headers=[
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

    @staticmethod
    def _native_json(payload, status=200):
        return request.make_json_response(wire_payload(payload, request.httprequest.path), status=status, headers=[
            ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
            ('Vary', 'Authorization'), ('X-Content-Type-Options', 'nosniff'),
        ])

    @staticmethod
    def _native_capability(grant_id, *, claim=False):
        """Native routes are capability-only: never silently fall back to WebView cookies."""
        incoming = request.httprequest
        if incoming.headers.get('Cookie') or incoming.args:
            raise ProtocolError('invalid_authentication', 'The upload capability is invalid.', 401)
        authorization = incoming.headers.get('Authorization', '')
        try:
            validate_headers(incoming.headers)
            token = upload_token(authorization)
        except ValueError:
            raise ProtocolError('invalid_authentication', 'The upload capability is invalid.', 401)
        supplied_id, separator, secret = token.partition('.')
        if not separator or supplied_id != grant_id or '.' in secret:
            raise ProtocolError('invalid_authentication', 'The upload capability is invalid.', 401)
        grants = request.env['baseer.bwork.mobile.upload.grant']
        return (grants._claim_capability(grant_id, secret) if claim
                else grants._status_capability(grant_id, secret))

    @staticmethod
    def _native_result(snapshot):
        payload = {
            'api_version': 2, 'grant_state': snapshot['state'],
            'upload_uuid': snapshot['upload_uuid'],
        }
        if snapshot['state'] == 'resolved':
            media = request.env['baseer.bwork.media'].sudo().browse(snapshot['media_id']).exists()
            if not media or media.upload_uuid != snapshot['upload_uuid']:
                raise ProtocolError('media_unavailable', 'The media result is unavailable.', 503)
            payload.update({'media_id': media.id, 'state': media.state})
        elif snapshot['state'] == 'denied':
            payload['failure_code'] = snapshot['failure_code']
        return payload

    @http.route(routes('/bwork/api/v2/rooms/<int:room_id>/mobile-upload-grants'), type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def issue_mobile_upload_grant(self, room_id, **kwargs):
        """Small same-origin WebView write.  It carries metadata, never file bytes."""
        try:
            incoming = request.httprequest
            if (incoming.args
                    or incoming.content_type.split(';', 1)[0].strip().lower()
                    != 'application/x-www-form-urlencoded'
                    or incoming.files or set(incoming.form) != {'csrf_token', 'metadata'}
                    or any(len(incoming.form.getlist(key)) != 1 for key in incoming.form)):
                raise ProtocolError('invalid_payload', 'Only a CSRF token and upload metadata are accepted.')
            if len(incoming.form['metadata'].encode('utf-8')) > 4096:
                raise ProtocolError('payload_too_large', 'Upload metadata is too large.', 413)
            return self._json(self._service()._v2_issue_mobile_upload_grant(
                room_id, parse_payload(incoming.form['metadata'])))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route(routes('/bwork/api/v2/rooms/<int:room_id>/uploads/<string:upload_uuid>/reconcile'),
                type='http', auth='user', methods=['GET'], csrf=False, save_session=True)
    def reconcile_mobile_upload(self, room_id, upload_uuid, **kwargs):
        """Session-authenticated read for a persisted local upload UUID after process loss."""
        try:
            if request.httprequest.args:
                raise ProtocolError('invalid_payload', 'Unexpected query fields.')
            return self._json(self._service()._v2_reconcile_native_upload(room_id, upload_uuid))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route(routes('/bwork/api/v2/mobile-upload-grants/<string:grant_id>'), type='http', auth='none',
                methods=['GET'], csrf=False, save_session=False)
    def native_upload_status(self, grant_id, **kwargs):
        try:
            incoming = request.httprequest
            if incoming.content_length not in (None, 0):
                raise ProtocolError('invalid_payload', 'This capability route does not accept a body.')
            snapshot = self._native_capability(grant_id)
            status = 200 if snapshot['state'] == 'resolved' else 202
            return self._native_json(self._native_result(snapshot), status)
        except (AccessError, ProtocolError) as error:
            return self._native_json({'api_version': 2, 'error': {
                'code': error.code if isinstance(error, ProtocolError) else 'forbidden',
                'message': str(error) if isinstance(error, ProtocolError) else 'This media is unavailable.',
            }}, error.status if isinstance(error, ProtocolError) else 403)

    @http.route(routes('/bwork/api/v2/mobile-upload-grants/<string:grant_id>/content'), type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False, max_content_length=MAX_UPLOAD_LIMIT)
    def native_upload_content(self, grant_id, **kwargs):
        snapshot = None
        try:
            incoming = request.httprequest
            snapshot = self._native_capability(grant_id, claim=True)
            if snapshot['state'] == 'resolved':
                return self._native_json(self._native_result(snapshot))
            if snapshot['state'] == 'uploading' and not snapshot.get('claimed'):
                return self._native_json(self._native_result(snapshot), 202)
            if (incoming.content_type.split(';', 1)[0].strip().lower() != snapshot['mime']
                    or incoming.content_length is None or incoming.content_length != snapshot['size']):
                raise ProtocolError('invalid_payload', 'The native upload body does not match its capability.')
            try:
                # Odoo's HTTPRequest deliberately exposes get_data(), not Werkzeug's
                # stream attribute. Content-Length has already been matched to the
                # capability and the route enforces MAX_UPLOAD_LIMIT before this read.
                raw = incoming.get_data(cache=False)
            except (OSError, ClientDisconnected) as interrupted:
                raise ProtocolError('upload_interrupted', 'The native upload stream was interrupted.', 408) from interrupted
            if len(raw) != snapshot['size']:
                raise ProtocolError('invalid_payload', 'The native upload body is incomplete.')
            service = request.env['baseer.bwork.service'].with_user(snapshot['user_id']).with_context({
                'allowed_company_ids': [snapshot['company_id']],
            })
            upload = service._v2_mobile_upload_from_capability(snapshot, raw)
            resolved = request.env['baseer.bwork.mobile.upload.grant']._resolve_claimed_capability(
                snapshot, upload['media_id'])
            return self._native_json(self._native_result(resolved))
        except TransactionRollbackError:
            # Odoo retries after a serialization/deadlock rollback.  The capability claim
            # is independent, so release this attempt before the retry sees ``uploading``.
            if snapshot and snapshot.get('claimed'):
                request.env['baseer.bwork.mobile.upload.grant']._release_claimed_capability(snapshot)
            raise
        except (AccessError, ProtocolError) as error:
            if snapshot and snapshot.get('state') == 'uploading':
                request.env['baseer.bwork.mobile.upload.grant']._deny_claimed_capability(
                    snapshot, error.code if isinstance(error, ProtocolError) else 'access_revoked')
            return self._native_json({'api_version': 2, 'error': {
                'code': error.code if isinstance(error, ProtocolError) else 'forbidden',
                'message': str(error) if isinstance(error, ProtocolError) else 'This media is unavailable.',
            }}, error.status if isinstance(error, ProtocolError) else 403)

    @http.route(routes('/bwork/api/v2/rooms/<int:room_id>/uploads'), type='http', auth='user',
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

    @http.route(routes('/bwork/api/v2/uploads/<int:media_id>/cancel'), type='http', auth='user',
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
            service = self._service()
            raw, mime, name = service._v2_media_content(media_id, thumbnail)
            # _v2_media_content still holds the room SHARE lock through response.
            revision = request.env['baseer.bwork.media'].sudo().browse(media_id).room_id.content_revision
            disposition = 'inline; filename="bwork-thumbnail.jpg"' if thumbnail else (
                'attachment; filename="bwork-file"; filename*=UTF-8\'\'' + quote(name, safe=''))
            return request.make_response(raw, status=200, headers=[
                ('Content-Type', mime), ('Content-Length', str(len(raw))),
                ('Content-Disposition', disposition),
                *response_header('X-BWork-Content-Revision', revision),
                ('Cache-Control', 'no-store'), ('Pragma', 'no-cache'),
                ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
                ('Content-Security-Policy', "default-src 'none'; sandbox"),
            ])
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route(routes('/bwork/api/v2/media/<int:media_id>/content'), type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def content(self, media_id, **kwargs):
        return self._content(media_id, False)

    @http.route(routes('/bwork/api/v2/media/<int:media_id>/thumbnail'), type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def thumbnail(self, media_id, **kwargs):
        return self._content(media_id, True)
