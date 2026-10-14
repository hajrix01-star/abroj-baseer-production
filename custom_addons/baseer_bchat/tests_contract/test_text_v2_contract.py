"""Fast offline checks for the BChat-only v2 wire contract."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from uuid import uuid1, uuid4


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'bchat_v2_contract_test_package'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for name in ('contracts', 'v2_contracts'):
    spec = importlib.util.spec_from_file_location('%s.%s' % (PACKAGE, name), ROOT / ('%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
v2 = sys.modules['%s.v2_contracts' % PACKAGE]


class BChatV2ContractTests(unittest.TestCase):
    def _payload(self, **changed):
        payload = {
            'api_version': 2, 'membership_id': 42,
            'client_uuid': str(uuid4()), 'text': 'BChat text',
        }
        payload.update(changed)
        return payload

    def test_exact_schema_and_uuidv4(self):
        for changed in ({'room_id': 7}, {'company_id': 1}, {'author_user_id': 2},
                        {'api_version': 1}, {'membership_id': True},
                        {'client_uuid': str(uuid1())}, {'text': '   '}):
            with self.subTest(changed=changed), self.assertRaises(v2.ProtocolError):
                v2.normalize_send(self._payload(**changed))

    def test_digest_covers_room_epoch_uuid_and_exact_text(self):
        normalized = v2.normalize_send(self._payload(text='  same  '))
        baseline = v2.digest(1, normalized)
        self.assertEqual(baseline, v2.digest(1, normalized))
        self.assertNotEqual(baseline, v2.digest(2, normalized))
        self.assertNotEqual(baseline, v2.digest(1, {**normalized, 'membership_id': 43}))
        self.assertNotEqual(baseline, v2.digest(1, {**normalized, 'text': 'same'}))

    def test_ack_is_not_claimed_until_service_supplies_persisted_id(self):
        normalized = v2.normalize_send(self._payload())
        self.assertEqual(v2.ack(9, normalized, 100), {
            'api_version': 2, 'room_id': 9, 'membership_id': 42,
            'client_uuid': normalized['client_uuid'], 'message_id': 100,
            'state': 'sent',
        })

    def test_document_selection_is_strict_and_digest_bound(self):
        original = self._payload(text='', media_id=7)
        normalized = v2.normalize_send(original)
        normalized['media_sha256'] = 'a' * 64
        legacy = v2.digest(1, normalized)
        for update in (
                {'document_type': 'invoice', 'policy_version': 2},
                {'document_type': 'payment_receipt', 'invoice_case_id': 9, 'policy_version': 2},
                {'document_type': 'other', 'policy_version': 2},
        ):
            selected = v2.normalize_send({**original, **update})
            selected['media_sha256'] = 'a' * 64
            self.assertNotEqual(v2.digest(1, selected), legacy)
        for key, changed in (
                ('document_type', 'payment_receipt'),
                ('invoice_case_id', 10),
                ('policy_version', 3),
        ):
            selected = v2.normalize_send({**original, 'document_type': 'invoice',
                                          'invoice_case_id': 9, 'policy_version': 2})
            selected['media_sha256'] = 'a' * 64
            self.assertNotEqual(v2.digest(1, selected), v2.digest(1, {**selected, key: changed}))
        for changed in (
                {'document_type': 'invoice'},
                {'document_type': 'Invoice', 'media_id': 7},
                {'document_type': 'invoice', 'media_id': 7, 'policy_version': True},
                {'invoice_case_id': 1, 'media_id': 7, 'policy_version': 0},
        ):
            with self.subTest(changed=changed), self.assertRaises(v2.ProtocolError):
                v2.normalize_send(self._payload(**changed))


if __name__ == '__main__':
    unittest.main()
