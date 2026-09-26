import json
import hashlib
import time

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import content_disposition, request


MAX_BODY = 128 * 1024
PAIR_ATTEMPTS = {}
PAIR_ATTEMPT_WINDOW_SECONDS = 60
MAX_PAIR_ATTEMPT_KEYS = 10000


class BaseerPrintAgentApi(http.Controller):
    def _response(self, payload, status=200):
        return request.make_json_response(payload, status=status, headers=[('Cache-Control', 'no-store')])

    def _invalid(self, status=401):
        return self._response({'error': 'unauthorized'}, status)

    def _runtime_id(self, data):
        if 'runtime_id' not in data:
            return ''  # Legacy agents remain usable until a modern runner owns the lease.
        runtime_id = data.get('runtime_id')
        return runtime_id if isinstance(runtime_id, str) and len(runtime_id) <= 128 else None

    def _runtime_allowed(self, agent, data):
        runtime_id = self._runtime_id(data)
        if runtime_id is None:
            return None
        return agent._claim_runtime(runtime_id)

    def _runtime_busy(self):
        return self._response({'error': 'agent_already_running'}, 409)

    @http.route('/baseer/print/agent-release/<int:release_id>/download', type='http', auth='user', methods=['GET'])
    def download_agent_release(self, release_id, **kwargs):
        """Serve an approved agent, optionally with a one-time connection envelope."""
        if not request.env.user.has_group('base.group_system'):
            return request.not_found()
        release = request.env['baseer.print.agent.release'].sudo().browse(release_id).exists()
        if not release or release.state != 'approved':
            return request.not_found()
        payload = release._artifact_bytes()
        filename = release.artifact_filename
        bootstrap_agent_id = kwargs.get('bootstrap_agent_id')
        if bootstrap_agent_id:
            try:
                bootstrap_agent_id = int(bootstrap_agent_id)
            except (TypeError, ValueError):
                return request.not_found()
            agent = request.env['baseer.print.agent'].sudo().browse(bootstrap_agent_id).exists()
            if (not agent or agent.state != 'new' or not agent.active
                    or not agent.device_uid.startswith(agent._PENDING_DEVICE_PREFIX)):
                return request.not_found()
            server_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            try:
                pairing_code = agent._generate_pairing_code()
                payload = release._bootstrap_artifact(server_url, pairing_code)
            except Exception:
                # The raw pairing secret must never be rendered or logged by a
                # failed download response.
                return request.not_found()
            filename = 'Baseer.PrintAgent-connect.exe'
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        return request.make_response(payload, headers=[
            ('Content-Type', 'application/vnd.microsoft.portable-executable'),
            ('Content-Length', str(len(payload))),
            ('Content-Disposition', content_disposition(filename)),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
            ('X-Baseer-Agent-Version', release.version),
            ('X-Baseer-Agent-SHA256', payload_sha256),
            ('X-Baseer-Agent-Release-SHA256', release.artifact_sha256),
        ])

    def _body(self):
        content_type = request.httprequest.headers.get('Content-Type', '')
        raw = request.httprequest.get_data(cache=False)
        if 'application/json' not in content_type or len(raw) > MAX_BODY:
            return False
        try:
            value = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return False
        return value if isinstance(value, dict) else False

    def _agent(self):
        authorization = request.httprequest.headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            return request.env['baseer.print.agent'].browse()
        return request.env['baseer.print.agent']._from_token(authorization[7:].strip())

    def _limited_pairing(self, device_uid=''):
        ip = request.httprequest.remote_addr or 'unknown'
        key = '%s:%s' % (ip, device_uid[:128])
        now = time.monotonic()
        for stale_key, stamps in list(PAIR_ATTEMPTS.items()):
            if not any(now - stamp < PAIR_ATTEMPT_WINDOW_SECONDS for stamp in stamps):
                PAIR_ATTEMPTS.pop(stale_key, None)
        if key not in PAIR_ATTEMPTS and len(PAIR_ATTEMPTS) >= MAX_PAIR_ATTEMPT_KEYS:
            # Bound unauthenticated in-memory state: callers beyond the limit
            # are rejected until an existing one-minute bucket expires.
            return True
        attempts = [stamp for stamp in PAIR_ATTEMPTS.get(key, []) if now - stamp < PAIR_ATTEMPT_WINDOW_SECONDS]
        attempts.append(now)
        PAIR_ATTEMPTS[key] = attempts
        return len(attempts) > 5

    @http.route('/baseer/print/v1/pair', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def pair(self, **kwargs):
        data = self._body()
        if not data or self._limited_pairing(data.get('device_uid', '') if isinstance(data.get('device_uid', ''), str) else ''):
            return self._invalid()
        code = data.get('pairing_code', '')
        device_uid = data.get('device_uid', '')
        version = data.get('agent_version', '')
        if not all(isinstance(value, str) for value in (code, device_uid, version)) or len(code) > 512:
            return self._invalid()
        pair = request.env['baseer.print.agent']._pair_device(code, device_uid, version)
        if not pair:
            return self._invalid()
        agent, token = pair
        return self._response({'token': token, 'agent_device_uid': agent.device_uid})

    @http.route('/baseer/print/v1/heartbeat', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def heartbeat(self, **kwargs):
        data, agent = self._body(), self._agent()
        if not data or not agent:
            return self._invalid()
        version = data.get('agent_version', '')
        if not isinstance(version, str):
            return self._response({'error': 'invalid_request'}, 400)
        runtime_id = self._runtime_id(data)
        if runtime_id is None:
            return self._response({'error': 'invalid_request'}, 400)
        if not agent._heartbeat(version, runtime_id):
            return self._runtime_busy()
        return self._response({'ok': True})

    @http.route('/baseer/print/v1/runtime/release', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def release_runtime(self, **kwargs):
        """Accept an exact local runtime handover; never release a job lease."""
        data, agent = self._body(), self._agent()
        if not data or not agent:
            return self._invalid()
        runtime_id = self._runtime_id(data)
        if runtime_id is None:
            return self._response({'error': 'invalid_request'}, 400)
        return self._response({'released': agent._release_runtime(runtime_id)})

    @http.route('/baseer/print/v1/printers/sync', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def sync_printers(self, **kwargs):
        data, agent = self._body(), self._agent()
        printers = data.get('printers') if data else None
        if not data or not agent:
            return self._invalid()
        runtime_allowed = self._runtime_allowed(agent, data)
        if runtime_allowed is None:
            return self._response({'error': 'invalid_request'}, 400)
        if not runtime_allowed:
            return self._runtime_busy()
        if not isinstance(printers, list) or len(printers) > 100:
            return self._response({'error': 'invalid_request'}, 400)
        clean = []
        for item in printers:
            if not isinstance(item, dict):
                return self._response({'error': 'invalid_request'}, 400)
            name, ident, driver = item.get('display_name'), item.get('machine_identifier'), item.get('driver_name', '')
            if (not isinstance(name, str) or not 0 < len(name) <= 256
                    or not isinstance(ident, str) or not 0 < len(ident) <= 256
                    or not isinstance(driver, str) or len(driver) > 256):
                return self._response({'error': 'invalid_request'}, 400)
            clean.append({'display_name': name, 'machine_identifier': ident, 'driver_name': driver})
        request.env['baseer.print.printer']._sync_from_agent(agent, clean)
        agent._heartbeat(runtime_id=self._runtime_id(data))
        return self._response({'ok': True})

    @http.route('/baseer/print/v1/jobs/claim', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def claim(self, **kwargs):
        data, agent = self._body(), self._agent()
        if data is False or not agent:
            return self._invalid()
        runtime_id = self._runtime_id(data)
        if runtime_id is None:
            return self._response({'error': 'invalid_request'}, 400)
        if not agent._heartbeat(data.get('agent_version') if isinstance(data.get('agent_version'), str) else False, runtime_id):
            return self._runtime_busy()
        job = request.env['baseer.print.job']._claim_for_agent(agent)
        return self._response({'job': job or None})

    def _job_action(self, job_id, action):
        data, agent = self._body(), self._agent()
        if not data or not agent or not isinstance(job_id, int):
            return self._invalid()
        runtime_allowed = self._runtime_allowed(agent, data)
        if runtime_allowed is None:
            return self._response({'error': 'invalid_request'}, 400)
        if not runtime_allowed:
            return self._runtime_busy()
        lease = data.get('lease_token', '')
        if not isinstance(lease, str) or len(lease) > 512:
            return self._invalid()
        job = request.env['baseer.print.job'].sudo().browse(job_id).exists()
        if not job:
            return self._invalid()
        try:
            if action == 'renew':
                return self._response({'lease_expires_at': job._renew_for_agent(agent, lease)})
            if action == 'complete':
                job._complete_for_agent(agent, lease)
            else:
                code = data.get('error_code', 'print_failed')
                retryable = bool(data.get('retryable', False))
                if not isinstance(code, str):
                    return self._response({'error': 'invalid_request'}, 400)
                job._fail_for_agent(agent, lease, code[:64], retryable)
        except AccessError:
            return self._invalid()
        return self._response({'ok': True})

    @http.route('/baseer/print/v1/jobs/<int:job_id>/renew', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def renew(self, job_id, **kwargs):
        return self._job_action(job_id, 'renew')

    @http.route('/baseer/print/v1/jobs/<int:job_id>/complete', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def complete(self, job_id, **kwargs):
        return self._job_action(job_id, 'complete')

    @http.route('/baseer/print/v1/jobs/<int:job_id>/fail', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def fail(self, job_id, **kwargs):
        return self._job_action(job_id, 'fail')
