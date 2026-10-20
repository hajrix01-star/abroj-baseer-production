"""Exercise the native HTTP body boundary with Odoo's actual request wrapper.

No database is needed: only capability storage and media persistence are mocked.
In particular, the body reader, form preprocessing, and JSON response are real.
"""
import inspect
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.test import EnvironBuilder

from odoo.http import HTTPRequest, Request
from odoo.tests import tagged
from odoo.tests.common import BaseCase

from ..controllers import media_api
from ..media_contracts import MAX_UPLOAD_LIMIT


@tagged('post_install', '-at_install', 'baseer_bwork_media')
class BWorkNativeUploadBodyCase(BaseCase):
    GRANT_ID = '11111111-1111-4111-8111-111111111111'
    UPLOAD_UUID = '22222222-2222-4222-8222-222222222222'
    # Synthetic test material, never an issued capability or an account token.
    SECRET = 'A' * 43
    BODY = b'synthetic-body'

    def setUp(self):
        super().setUp()
        self.controller = media_api.BWorkMediaApi()
        self.grants = MagicMock()
        self.service = MagicMock()
        self.service.with_user.return_value = self.service
        self.service.with_context.return_value = self.service
        self.service._v2_mobile_upload_from_capability.return_value = {'media_id': 17}
        self.media = MagicMock()
        self.media.sudo.return_value = self.media
        self.media.browse.return_value = self.media
        self.media.exists.return_value = SimpleNamespace(
            id=17, upload_uuid=self.UPLOAD_UUID, state='staged')

    def _incoming(self, body=None, *, declared_size=None, mime='image/jpeg'):
        body = self.BODY if body is None else body
        builder = EnvironBuilder(
            method='POST', path='/bwork/api/v2/mobile-upload-grants/test/content',
            input_stream=io.BytesIO(body), content_type=mime,
            headers={'Authorization': f'BWorkUpload {self.GRANT_ID}.{self.SECRET}'})
        self.addCleanup(builder.close)
        environ = builder.get_environ()
        if declared_size is not None:
            environ['CONTENT_LENGTH'] = str(declared_size)
        incoming = HTTPRequest(environ)
        # The dispatcher applies this route value before get_http_params().
        incoming.max_content_length = (
            self.controller.native_upload_content.original_routing['max_content_length'])
        self.assertEqual(incoming.max_content_length, MAX_UPLOAD_LIMIT)
        # HttpDispatcher.get_http_params() accesses both before the controller.
        self.assertFalse(incoming.form)
        self.assertFalse(incoming.files)
        return incoming

    def _invoke(self, incoming, *, expected_size=None, state='uploading'):
        snapshot = {
            'state': state, 'claimed': state == 'uploading',
            'mime': incoming.content_type, 'size': (
                incoming.content_length if expected_size is None else expected_size),
            'user_id': 7, 'company_id': 3, 'upload_uuid': self.UPLOAD_UUID,
            'media_id': 17,
        }
        self.grants._claim_capability.return_value = snapshot
        self.grants._resolve_claimed_capability.return_value = {
            **snapshot, 'state': 'resolved', 'media_id': 17,
        }
        actual_request = Request(incoming)
        actual_request.env = {
            'baseer.bwork.mobile.upload.grant': self.grants,
            'baseer.bwork.service': self.service,
            'baseer.bwork.media': self.media,
        }
        endpoint = inspect.unwrap(type(self.controller).native_upload_content)
        with patch.object(media_api, 'request', actual_request):
            return endpoint(self.controller, self.GRANT_ID)

    def _assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(json.loads(response.get_data())['error']['code'], code)
        self.service._v2_mobile_upload_from_capability.assert_not_called()
        self.grants._resolve_claimed_capability.assert_not_called()

    def test_valid_body_survives_real_odoo_form_preprocessing(self):
        """Regression: HTTPRequest exposes get_data(), but no stream attribute."""
        incoming = self._incoming()
        response = self._invoke(incoming)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_data()), {
            'api_version': 2, 'grant_state': 'resolved',
            'upload_uuid': self.UPLOAD_UUID, 'media_id': 17, 'state': 'staged',
        })
        self.service._v2_mobile_upload_from_capability.assert_called_once()
        self.assertEqual(self.service._v2_mobile_upload_from_capability.call_args.args[1],
                         self.BODY)
        self.grants._deny_claimed_capability.assert_not_called()
        self.grants._resolve_claimed_capability.assert_called_once()

    def test_exact_route_limit_remains_readable(self):
        body = b'x' * MAX_UPLOAD_LIMIT
        response = self._invoke(self._incoming(body, mime='application/pdf'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service._v2_mobile_upload_from_capability.call_args.args[1],
                         body)

    def test_route_rejects_body_above_limit_before_claim(self):
        with self.assertRaises(RequestEntityTooLarge):
            self._incoming(b'x' * (MAX_UPLOAD_LIMIT + 1), mime='application/pdf')
        self.grants._claim_capability.assert_not_called()
        self.service._v2_mobile_upload_from_capability.assert_not_called()

    def test_content_length_must_match_claim_before_reading(self):
        incoming = self._incoming()
        with patch.object(HTTPRequest, 'get_data', wraps=incoming.get_data) as reader:
            response = self._invoke(incoming, expected_size=len(self.BODY) + 1)
        self._assert_error(response, 400, 'invalid_payload')
        reader.assert_not_called()

    def test_disconnected_real_stream_is_408_and_cannot_persist_media(self):
        incoming = self._incoming(declared_size=len(self.BODY) + 1)
        response = self._invoke(incoming)
        self._assert_error(response, 408, 'upload_interrupted')
        self.assertEqual(self.grants._deny_claimed_capability.call_args.args[1],
                         'upload_interrupted')

    def test_short_body_result_is_rejected_before_persistence(self):
        incoming = self._incoming()
        with patch.object(HTTPRequest, 'get_data', return_value=self.BODY[:-1]):
            response = self._invoke(incoming)
        self._assert_error(response, 400, 'invalid_payload')

    def test_io_failure_is_reported_as_interrupted(self):
        incoming = self._incoming()
        with patch.object(HTTPRequest, 'get_data', side_effect=OSError('synthetic I/O failure')):
            response = self._invoke(incoming)
        self._assert_error(response, 408, 'upload_interrupted')

    def test_programming_error_is_not_reported_as_network_interruption(self):
        incoming = self._incoming()
        with patch.object(HTTPRequest, 'get_data', side_effect=AttributeError('synthetic bug')):
            with self.assertRaisesRegex(AttributeError, 'synthetic bug'):
                self._invoke(incoming)
        self.grants._deny_claimed_capability.assert_not_called()
        self.service._v2_mobile_upload_from_capability.assert_not_called()

    def test_resolved_claim_returns_receipt_without_reading_or_saving_again(self):
        incoming = self._incoming()
        with patch.object(HTTPRequest, 'get_data', wraps=incoming.get_data) as reader:
            response = self._invoke(incoming, state='resolved')
        self.assertEqual(response.status_code, 200)
        reader.assert_not_called()
        self.service._v2_mobile_upload_from_capability.assert_not_called()
        self.grants._resolve_claimed_capability.assert_not_called()
