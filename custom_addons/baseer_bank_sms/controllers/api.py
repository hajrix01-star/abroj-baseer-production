import json

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request


class BaseerBankSmsApi(http.Controller):
    """Private device-to-Odoo ingestion endpoint.

    It is intentionally narrow: no model/method/domain is accepted from the
    phone and no raw SMS body is written to technical logs.
    """

    @http.route('/baseer-bank-sms/v1/pair', type='http', auth='none', methods=['POST'], csrf=False)
    def pair_phone(self, **_kwargs):
        try:
            payload = request.httprequest.get_json(force=False, silent=False)
        except Exception:
            return request.make_json_response({'error': 'invalid_json'}, status=400)
        if not isinstance(payload, dict) or set(payload) != {'pairing_token', 'installation_id'}:
            return request.make_json_response({'error': 'invalid_payload'}, status=400)
        token = payload.get('pairing_token')
        if not isinstance(token, str) or not 20 <= len(token) <= 120:
            return request.make_json_response({'error': 'invalid_pairing_token'}, status=400)
        pairing = request.env['baseer.bank.sms.pairing'].sudo().search([('token', '=', token)], limit=1)
        if not pairing:
            return request.make_json_response({'error': 'invalid_pairing_token'}, status=404)
        try:
            configuration = pairing.consume(payload.get('installation_id'))
        except ValidationError:
            return request.make_json_response({'error': 'pairing_unavailable'}, status=409)
        return request.make_json_response({'status': 'paired', **configuration}, status=200)

    @http.route('/baseer-bank-sms/v2/pair', type='http', auth='none', methods=['POST'], csrf=False)
    def pair_phone_v2(self, **_kwargs):
        """Fresh-client pairing; intentionally separate from the legacy v1 app."""
        try:
            payload = request.httprequest.get_json(force=False, silent=False)
        except Exception:
            return request.make_json_response({'error': 'invalid_json'}, status=400)
        if not isinstance(payload, dict) or set(payload) != {'pairing_token', 'installation_id'}:
            return request.make_json_response({'error': 'invalid_payload'}, status=400)
        token, installation_id = payload.get('pairing_token'), payload.get('installation_id')
        if not isinstance(token, str) or not 20 <= len(token) <= 120 or not isinstance(installation_id, str) or not 8 <= len(installation_id) <= 80:
            return request.make_json_response({'error': 'invalid_pairing_token'}, status=400)
        pairing = request.env['baseer.bank.sms.pairing'].sudo().search([('token', '=', token)], limit=1)
        if not pairing:
            return request.make_json_response({'error': 'invalid_pairing_token'}, status=404)
        try:
            configuration = pairing.consume(installation_id)
        except ValidationError:
            return request.make_json_response({'error': 'pairing_unavailable'}, status=409)
        return request.make_json_response({'status': 'paired', 'protocol_version': '2', **configuration}, status=200)

    @http.route('/baseer-bank-sms/v1/messages', type='http', auth='none', methods=['POST'], csrf=False)
    def ingest_message(self, **_kwargs):
        authorization = request.httprequest.headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            return request.make_json_response({'error': 'missing_device_credential'}, status=401)
        try:
            payload = request.httprequest.get_json(force=False, silent=False)
        except Exception:
            return request.make_json_response({'error': 'invalid_json'}, status=400)
        if not isinstance(payload, dict):
            return request.make_json_response({'error': 'invalid_payload'}, status=400)

        Device = request.env['baseer.bank.sms.device'].sudo()
        device = Device.search([('device_code', '=', payload.get('device_code'))], limit=1)
        if not device or not device.verify_secret(authorization[7:]):
            return request.make_json_response({'error': 'invalid_device_credential'}, status=401)
        existing = request.env['baseer.bank.sms.message'].sudo().search([
            ('source_device_id', '=', device.device_code),
            ('idempotency_key', '=', payload.get('idempotency_key')),
        ], limit=1)
        if existing:
            return request.make_json_response({'id': existing.id, 'status': 'accepted', 'duplicate': True}, status=200)
        try:
            message = device.ingest_payload(payload)
        except ValueError as error:
            return request.make_json_response({'error': str(error)}, status=400)
        except Exception:
            # Keep technical details and SMS content out of the HTTP response.
            return request.make_json_response({'error': 'ingestion_unavailable'}, status=503)
        return request.make_json_response({
            'id': message.id,
            'status': 'accepted',
            'duplicate': False,
        }, status=200)

    def _authenticated_device(self, payload):
        authorization = request.httprequest.headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            return None, request.make_json_response({'error': 'missing_device_credential'}, status=401)
        if not isinstance(payload, dict):
            return None, request.make_json_response({'error': 'invalid_payload'}, status=400)
        device = request.env['baseer.bank.sms.device'].sudo().search([
            ('device_code', '=', payload.get('device_code')),
        ], limit=1)
        if not device or not device.verify_secret(authorization[7:]):
            return None, request.make_json_response({'error': 'invalid_device_credential'}, status=401)
        return device, None

    @http.route('/baseer-bank-sms/v2/messages', type='http', auth='none', methods=['POST'], csrf=False)
    def ingest_messages_v2(self, **_kwargs):
        """Bounded acknowledgement batch: permanent rejection never blocks later messages."""
        try:
            payload = request.httprequest.get_json(force=False, silent=False)
        except Exception:
            return request.make_json_response({'error': 'invalid_json'}, status=400)
        device, error = self._authenticated_device(payload)
        if error:
            return error
        if set(payload) != {'device_code', 'messages'} or not isinstance(payload.get('messages'), list) or not payload['messages'] or len(payload['messages']) > 50:
            return request.make_json_response({'error': 'invalid_batch'}, status=400)
        acknowledgements = []
        Message = request.env['baseer.bank.sms.message'].sudo()
        for item in payload['messages']:
            key = item.get('idempotency_key') if isinstance(item, dict) else None
            if not isinstance(key, str):
                acknowledgements.append({'idempotency_key': '', 'status': 'blocked', 'reason': 'invalid_idempotency_key'})
                continue
            # A v2 client keeps its installation id across re-pairing.  The
            # history token is therefore stable even though a replacement
            # device credential has a new device_code.
            existing = Message.search([('idempotency_key', '=', key)], limit=1)
            if existing:
                acknowledgements.append({'idempotency_key': key, 'status': 'duplicate'})
                continue
            try:
                device.ingest_payload({'device_code': device.device_code, **item})
                acknowledgements.append({'idempotency_key': key, 'status': 'accepted'})
            except ValueError as validation_error:
                reason = str(validation_error)
                acknowledgements.append({'idempotency_key': key, 'status': 'retryable' if reason == 'rate_limit_exceeded' else 'blocked', 'reason': reason})
            except Exception:
                acknowledgements.append({'idempotency_key': key, 'status': 'retryable', 'reason': 'ingestion_unavailable'})
        return request.make_json_response({'acknowledgements': acknowledgements}, status=200)

    @http.route('/baseer-bank-sms/v2/device/heartbeat', type='http', auth='none', methods=['POST'], csrf=False)
    def device_heartbeat_v2(self, **_kwargs):
        """Authenticated, metadata-only heartbeat for an honest device status."""
        try:
            payload = request.httprequest.get_json(force=False, silent=False)
        except Exception:
            return request.make_json_response({'error': 'invalid_json'}, status=400)
        device, error = self._authenticated_device(payload)
        if error:
            return error
        try:
            status = device.record_heartbeat(payload)
        except ValueError as validation_error:
            return request.make_json_response({'error': str(validation_error)}, status=400)
        return request.make_json_response({'status': 'ok', **status}, status=200)

    @http.route('/baseer-bank-sms/v2/device/config', type='http', auth='none', methods=['GET'], csrf=False)
    def device_config_v2(self, device_code=None, **_kwargs):
        """Versioned sender policy.  It does not change the device heartbeat."""
        payload = {'device_code': device_code}
        device, error = self._authenticated_device(payload)
        if error:
            return error
        sender_records = request.env['baseer.bank.sms.sender'].sudo().search([('active', '=', True)], order='sender, id')
        senders = sender_records.mapped('sender')
        revision = '|'.join('%s:%s' % (record.id, record.write_date) for record in sender_records)
        return request.make_json_response({
            'senders': senders,
            'policy_revision': revision,
            'environment_label': request.env['ir.config_parameter'].sudo().get_param(
                'baseer_bank_sms.environment_label', 'QA'),
        }, status=200)

    @http.route('/baseer-bank-sms/v1/config', type='http', auth='none', methods=['GET'], csrf=False)
    def device_config(self, device_code=None, **_kwargs):
        authorization = request.httprequest.headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            return request.make_json_response({'error': 'missing_device_credential'}, status=401)
        device = request.env['baseer.bank.sms.device'].sudo().search([('device_code', '=', device_code)], limit=1)
        if not device or not device.verify_secret(authorization[7:]):
            return request.make_json_response({'error': 'invalid_device_credential'}, status=401)
        device.mark_seen()
        senders = request.env['baseer.bank.sms.sender'].sudo().search([('active', '=', True)]).mapped('sender')
        return request.make_json_response({'senders': senders}, status=200)
