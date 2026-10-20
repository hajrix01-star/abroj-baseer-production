"""Offline tests: python3 -m unittest discover -s .../tests_contract -v."""
import ast
import csv
import importlib.util
import json
from pathlib import Path
import unittest
from uuid import uuid1, uuid4
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bwork_contracts', ROOT / 'contracts.py')
contracts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contracts)


def envelope(**overrides):
    payload = {'api_version': 1, 'company_id': 10, 'channel_id': 20,
               'client_uuid': '17d4378a-b218-427c-887e-7ddac57b7a8f',
               'text': 'مرحبا BWork', 'attachment_ids': [], 'reply_to_id': None}
    payload.update(overrides)
    return payload


class ContractTests(unittest.TestCase):
    def test_message_round_trip_preserves_text(self):
        raw = json.dumps(envelope(text='  hello\nworld  '))
        actual = contracts.normalize_message(contracts.parse_payload(raw))
        self.assertEqual(actual['text'], '  hello\nworld  ')

    def test_uuid_uppercase_is_canonical(self):
        uuid = str(uuid4())
        self.assertEqual(contracts.canonical_uuid(uuid.upper()), uuid)

    def test_uuid_must_be_v4_and_hyphenated(self):
        for bad in [None, True, str(uuid1()), '0' * 36, uuid4().hex, '{' + str(uuid4()) + '}']:
            with self.subTest(bad=bad), self.assertRaises(contracts.ProtocolError):
                contracts.canonical_uuid(bad)

    def test_record_ids_reject_bool_float_strings_and_overflow(self):
        for bad in [None, True, 1.0, '1', 0, -1, 2 ** 40]:
            for field in ['company_id', 'channel_id']:
                with self.subTest(field=field, bad=bad), self.assertRaises(contracts.ProtocolError):
                    contracts.normalize_message(envelope(**{field: bad}))

    def test_unknown_fields_and_missing_fields_rejected(self):
        for field in ['uid', 'author_id', 'context', 'access_token', 'model', 'payload_digest']:
            with self.subTest(field=field), self.assertRaises(contracts.ProtocolError):
                contracts.normalize_message(envelope(**{field: 1}))
        payload = envelope()
        del payload['reply_to_id']
        with self.assertRaises(contracts.ProtocolError):
            contracts.normalize_message(payload)

    def test_api_version_strict(self):
        for value in [True, '1', 1.0, 0, 2]:
            with self.subTest(value=value), self.assertRaises(contracts.ProtocolError):
                contracts.normalize_message(envelope(api_version=value))

    def test_empty_and_invalid_text(self):
        for value in ['', ' \n', None, 42, 'a\x00b', '\ud800']:
            with self.subTest(value=value), self.assertRaises(contracts.ProtocolError):
                contracts.normalize_message(envelope(text=value))

    def test_text_utf8_byte_limit(self):
        contracts.normalize_message(envelope(text='x' * contracts.MAX_TEXT_BYTES))
        with self.assertRaises(contracts.ProtocolError):
            contracts.normalize_message(envelope(text='ع' * (contracts.MAX_TEXT_BYTES // 2 + 1)))

    def test_raw_markup_remains_plain_text(self):
        text = '<img src=x onerror=alert(1)>'
        self.assertEqual(contracts.normalize_message(envelope(text=text))['text'], text)
        # A future native writer must use body as str, never Markup/body_is_html.

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(contracts.ProtocolError):
            contracts.parse_payload('{"company_id":1,"company_id":2}')

    def test_malformed_json_and_nonobjects_rejected(self):
        for raw in [None, '[]', 'null', 'true', '1', '{bad', '{"x":NaN}', '{"x":Infinity}']:
            with self.subTest(raw=raw), self.assertRaises(contracts.ProtocolError):
                contracts.parse_payload(raw)

    def test_overlarge_raw_payload(self):
        with self.assertRaises(contracts.ProtocolError) as error:
            contracts.parse_payload(' ' * (contracts.MAX_PAYLOAD_BYTES + 1))
        self.assertEqual(error.exception.status, 413)

    def test_nested_payload_is_bounded(self):
        with self.assertRaises(contracts.ProtocolError):
            contracts.parse_payload('[' * 5000 + ']' * 5000)

    def test_attachments_fail_closed(self):
        with self.assertRaises(contracts.ProtocolError) as error:
            contracts.normalize_message(envelope(attachment_ids=[1]))
        self.assertEqual(error.exception.code, 'capability_unavailable')
        for bad in ['1', [True], [-1], None, [1] * 21]:
            with self.subTest(bad=bad), self.assertRaises(contracts.ProtocolError):
                contracts.normalize_message(envelope(attachment_ids=bad))

    def test_reply_parent_fail_closed(self):
        with self.assertRaises(contracts.ProtocolError) as error:
            contracts.normalize_message(envelope(reply_to_id=1))
        self.assertEqual(error.exception.code, 'capability_unavailable')
        with self.assertRaises(contracts.ProtocolError):
            contracts.normalize_message(envelope(reply_to_id=True))

    def test_digest_deterministic_across_key_order(self):
        payload = contracts.normalize_message(envelope())
        reversed_payload = dict(reversed(list(payload.items())))
        self.assertEqual(contracts.payload_digest(payload), contracts.payload_digest(reversed_payload))
        self.assertEqual(len(contracts.payload_digest(payload)), 64)

    def test_digest_covers_text_and_tenant_target(self):
        baseline = contracts.payload_digest(contracts.normalize_message(envelope()))
        for overrides in [{'text': 'other'}, {'company_id': 11}, {'channel_id': 21},
                          {'client_uuid': str(uuid4())}]:
            with self.subTest(overrides=overrides):
                self.assertNotEqual(baseline, contracts.payload_digest(contracts.normalize_message(envelope(**overrides))))

    def test_replay_returns_same_native_message(self):
        payload = contracts.normalize_message(envelope())
        digest = contracts.payload_digest(payload)
        ack = contracts.replay_ack(payload, digest, 99)
        self.assertEqual(ack, contracts.persisted_ack(payload, 99))
        self.assertEqual(ack['state'], 'sent')
        self.assertNotIn('delivered', ack)
        self.assertNotIn('read', ack)

    def test_changed_payload_conflicts(self):
        payload = contracts.normalize_message(envelope())
        changed = contracts.normalize_message(envelope(text='changed'))
        with self.assertRaises(contracts.ProtocolError) as error:
            contracts.replay_ack(changed, contracts.payload_digest(payload), 99)
        self.assertEqual((error.exception.code, error.exception.status), ('idempotency_conflict', 409))

    def test_ack_requires_real_positive_native_id(self):
        for value in [None, 0, -1, True, 'pending']:
            with self.subTest(value=value), self.assertRaises(contracts.ProtocolError):
                contracts.persisted_ack(envelope(), value)

    def test_conversation_contract(self):
        payload = {'api_version': 1, 'company_id': 10, 'client_uuid': str(uuid4()),
                   'name': 'Branch', 'member_user_ids': [4, 2]}
        self.assertEqual(contracts.normalize_conversation(payload)['member_user_ids'], [2, 4])
        for value in [[], [2, 2], [True], list(range(1, 52)), '2']:
            with self.subTest(value=value), self.assertRaises(contracts.ProtocolError):
                contracts.normalize_conversation(dict(payload, member_user_ids=value))

    def test_capabilities_are_unconditionally_disabled(self):
        bootstrap = contracts.capabilities()
        self.assertFalse(bootstrap['integration_enabled'])
        self.assertFalse(any(bootstrap['capabilities'].values()))
        self.assertTrue(bootstrap['history_policy']['activation_blocked'])
        self.assertFalse(bootstrap['history_policy']['enforced_globally'])
        with self.assertRaises(contracts.ProtocolError) as error:
            contracts.require_released()
        self.assertEqual((error.exception.code, error.exception.status), ('integration_disabled', 503))

    def test_capabilities_are_not_mutable_global_state(self):
        first = contracts.capabilities()
        first['capabilities']['messages'] = True
        first['release_blockers'].clear()
        self.assertFalse(contracts.capabilities()['capabilities']['messages'])
        self.assertTrue(contracts.capabilities()['release_blockers'])


class SourceBoundaryTests(unittest.TestCase):
    """Static regression guardrails, NOT proof of Odoo ACL/runtime behavior."""
    def test_routes_require_native_session_and_csrf(self):
        tree = ast.parse((ROOT / 'controllers/api.py').read_text())
        routes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'route':
                keywords = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
                self.assertEqual(keywords['auth'], 'user')
                self.assertEqual(keywords['type'], 'http')
                self.assertIs(keywords['csrf'], True)
                self.assertNotIn('cors', keywords)
                routes.append(node)
        self.assertEqual(len(routes), 3)

    def test_service_methods_are_private(self):
        tree = ast.parse((ROOT / 'models/service.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                self.assertTrue(node.name.startswith('_'), node.name)

    def test_v1_has_no_sudo_token_login_or_native_business_writer(self):
        prohibited = {'sudo', 'authenticate', 'message_post', 'action_post', 'action_approve', 'action_set_stage'}
        # The reviewed v2 BWork-only service uses narrowly scoped sudo after
        # explicit room, company and membership checks. Legacy v1 stays gated.
        legacy = ['models/service.py', 'models/binding.py', 'models/receipt.py', 'controllers/api.py']
        for name in legacy:
            path = ROOT / name
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, prohibited, path)

    def test_receipt_acl_read_only_and_tenant_rules_global(self):
        with (ROOT / 'security/ir.model.access.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        rows = [row for row in rows if row['model_id:id'] == 'model_baseer_bwork_receipt']
        self.assertEqual(len(rows), 1)
        self.assertEqual([rows[0][field] for field in ['perm_write', 'perm_create', 'perm_unlink']], ['0', '0', '0'])
        xml = ET.parse(ROOT / 'security/security.xml')
        rules = xml.findall(".//record[@model='ir.rule']")
        self.assertEqual(len(rules), 7)
        for rule in rules:
            self.assertIsNone(rule.find("field[@name='groups']"))
        self.assertFalse(xml.findall(".//field[@name='users']"))
        self.assertFalse(xml.findall(".//field[@name='user_ids']"))

    def test_explicit_manager_app_without_automatic_install_demo_or_cron(self):
        manifest = ast.literal_eval((ROOT / '__manifest__.py').read_text())
        self.assertFalse(manifest['auto_install'])
        self.assertTrue(manifest['application'])
        self.assertIn('views/bwork_admin_views.xml', manifest['data'])
        self.assertNotIn('demo', manifest)
        xml = ET.parse(ROOT / 'security/security.xml')
        self.assertFalse(xml.findall(".//record[@model='ir.cron']"))


if __name__ == '__main__':
    unittest.main()
