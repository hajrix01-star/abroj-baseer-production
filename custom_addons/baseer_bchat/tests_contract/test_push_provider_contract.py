"""Behavioural provider fixtures; no Odoo, Firebase credential, or network."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'bchat_push_provider_contract', Path(__file__).resolve().parents[1] / 'push_contracts.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)


class PushProviderContractCase(unittest.TestCase):
    def test_actual_v1_unregistered_envelope_is_permanent(self):
        failure = provider.classify_fcm_failure(404, {'error': {
            'code': 404, 'status': 'NOT_FOUND', 'message': 'synthetic fixture',
            'details': [{'@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError',
                         'errorCode': 'UNREGISTERED'}],
        }})
        self.assertEqual(failure, {'code': 'unregistered', 'retry': False,
                                   'invalid_token': True, 'retry_after': None})

    def test_http_404_or_untyped_detail_does_not_revoke_a_token(self):
        for payload in (None, {}, {'error': {'status': 'UNREGISTERED'}},
                        {'error': {'details': [{'errorCode': 'UNREGISTERED'}]}},
                        {'error': {'details': ['UNREGISTERED']}},
                        {'error': {'details': {'errorCode': 'UNREGISTERED'}}}):
            with self.subTest(payload=payload):
                failure = provider.classify_fcm_failure(404, payload)
                self.assertFalse(failure['invalid_token'])
                self.assertEqual(failure['code'], 'configuration')

    def test_transient_quota_and_unavailable_respect_provider_seconds(self):
        for status in (429, 503):
            failure = provider.classify_fcm_failure(status, {}, '120')
            self.assertTrue(failure['retry'])
            self.assertFalse(failure['invalid_token'])
            self.assertEqual(failure['retry_after'], 120)
            self.assertGreaterEqual(provider.retry_delay_seconds(1, 120, 0.15), 120)

    def test_retry_after_accepts_http_date_and_clamps_invalid_or_past_values(self):
        now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        self.assertEqual(provider.retry_after_seconds('Sat, 17 Oct 2026 12:02:00 GMT', now), 120)
        self.assertEqual(provider.retry_after_seconds('Sat, 17 Oct 2026 11:02:00 GMT', now), 0)
        self.assertEqual(provider.retry_after_seconds('99999999999', now), 86400)
        for value in (None, '', '-3', 'not a date', '1' * 129):
            self.assertIsNone(provider.retry_after_seconds(value, now))

    def test_backoff_is_positive_exponential_and_jitter_is_bounded(self):
        self.assertEqual(provider.retry_delay_seconds(1, None, 0), 60)
        self.assertEqual(provider.retry_delay_seconds(2, None, 0), 120)
        self.assertEqual(provider.retry_delay_seconds(4, None, 0), 480)
        self.assertEqual(provider.retry_delay_seconds(1, 120, 0.2), 144)
        self.assertEqual(provider.retry_delay_seconds(1, 120, 200), 144)
        self.assertEqual(provider.retry_delay_seconds(100000, 86400, 0.2), 86400)

    def test_invalid_payload_is_permanent_but_auth_is_configuration(self):
        invalid = provider.classify_fcm_failure(400, {'error': {'status': 'INVALID_ARGUMENT'}})
        self.assertFalse(invalid['retry'])
        self.assertEqual(invalid['code'], 'invalid_payload')
        for status in (401, 403):
            self.assertEqual(provider.classify_fcm_failure(status, {})['code'], 'configuration')


if __name__ == '__main__':
    unittest.main()
