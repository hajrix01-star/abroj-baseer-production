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
