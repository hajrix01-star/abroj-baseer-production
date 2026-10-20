"""Pure retention codecs/scheduling, never a substitute for isolated Odoo."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
import ast
import xml.etree.ElementTree as ET
from types import SimpleNamespace
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType('_bwork_retention_contract')
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetentionContractTests(unittest.TestCase):
    def test_actual_attachment_fingerprint_changes_when_same_id_metadata_changes(self):
        # Execute the production methods, not a duplicate hash calculation.
        source = (ROOT / 'models/retention.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and node.name in ('_retention_fingerprint', '_retention_attachment_fingerprint')]
        for method in methods:
            method.decorator_list = []
        token = object()
        namespace = {'_RETENTION_TOKEN': token, 'AccessError': RuntimeError,
                     'hashlib': hashlib, 'json': json,
                     'fields': SimpleNamespace(Datetime=SimpleNamespace(to_string=lambda value: value))}
        exec(compile(ast.Module(body=methods, type_ignores=[]), '<actual-retention-fingerprint>', 'exec'), namespace)
        service = type('ProductionMethods', (), {method.name: namespace[method.name] for method in methods})()

        class Files:
            def __init__(self, rows):
                self.rows = rows
                self._fields = {}
                self.id = rows[0].id if rows else False
            def __or__(self, other):
                return Files(self.rows + other.rows)
            def sudo(self):
                return self
            def exists(self):
                return self
            def flush_recordset(self, names):
                pass
            def sorted(self, key):
                return sorted(self.rows, key=lambda row: row.id)

        attachment = SimpleNamespace(id=6, checksum='old', file_size=10, write_date='2026-10-20 01:00:00',
            type='binary', res_model='baseer.bwork.media', res_id=5, company_id=SimpleNamespace(id=2),
            public=False, access_token=False, res_field=False, _fields={})
        media = SimpleNamespace(id=5, retention_state='active', attachment_id=Files([attachment]),
            thumbnail_attachment_id=Files([]), document_file_id=0, document_type='other')
        message = SimpleNamespace(id=4, company_id=SimpleNamespace(id=2), retention_state='active',
            retention_preserved=False, payload_digest='fixed', create_date='2026-09-01 00:00:00', media_id=media)
        before = service._retention_fingerprint(message, token)
        attachment.checksum, attachment.file_size = 'new', 20
        self.assertNotEqual(service._retention_fingerprint(message, token), before)

    def test_strict_reconciliation_and_scope_bound_cursor(self):
        wire = load(package.__name__ + '.retention_contracts', ROOT / 'retention_contracts.py')
        request = {'api_version': 2, 'membership_id': 4, 'content_revision': 0, 'media_ids': [1, 2]}
        self.assertEqual(wire.reconcile_payload(request), (4, 0, [1, 2], None))
        for value in ([2, 1], [1, 1], [True], list(range(1, 202))):
            with self.assertRaises(wire.ProtocolError):
                wire.reconcile_payload(dict(request, media_ids=value))
        scope = [2, 3, 4, 5, 0, wire.ids_digest([1, 2])]
        token = wire.cursor_for(scope, 1)
        self.assertLessEqual(len(token), 256)
        self.assertEqual(wire.cursor_index(token, scope, 2), 1)
        with self.assertRaises(wire.ProtocolError):
            wire.cursor_index(token, [2, 3, 4, 5, 1, scope[-1]], 2)

    def test_integer_bytes_and_schedule_gap_fold(self):
        from datetime import datetime
        rules = load('_bwork_retention_rules', ROOT.parent / 'baseer_bwork_admin/retention_contracts.py')
        self.assertEqual(rules.size_label(1536), '1.50 KiB')
        self.assertEqual(rules.size_label(3000000000), '2.79 GiB')
        self.assertEqual(rules.size_label(100000 * 10 * 1024 ** 2), '976.56 GiB')
        self.assertEqual(rules.cutoff('before_date', '2026-10-20', 0, 'Asia/Riyadh', datetime(2026, 10, 20)), datetime(2026, 10, 19, 21))
        self.assertEqual(rules.local_slot('2026-03-08', '02', '30', 'America/New_York'), datetime(2026, 3, 8, 7))
        self.assertEqual(rules.local_slot('2026-11-01', '01', '30', 'America/New_York'), datetime(2026, 11, 1, 5, 30))
        for days in (True, 0, -1, 36501):
            with self.assertRaises(ValueError):
                rules.cutoff('older_than_days', None, days, 'UTC', datetime(2026, 10, 20))

    def test_gallery_search_literal_bytes_and_revision_bound_cursor(self):
        wire = load(package.__name__ + '.gallery_contracts', ROOT / 'gallery_contracts.py')
        self.assertEqual(wire.search_pattern('a%_\\b'), '%a\\%\\_\\\\b%')
        self.assertEqual(wire.search('ع' * 64), 'ع' * 64)
        for bad in ('ع' * 65, 'a\x00b', True):
            with self.assertRaises(wire.ProtocolError):
                wire.search(bad)
        token = wire.cursor_for(3, 4, 'all', 'largest', 5, 100, 2, 'x%')
        self.assertEqual(wire.anchor(token, 3, 4, 'all', 'largest', 2, 'x%'), (5, 100))
        for revision, q in ((3, 'x%'), (2, 'x_')):
            with self.assertRaises(wire.ProtocolError):
                wire.anchor(token, 3, 4, 'all', 'largest', revision, q)

    def test_native_count_pins_and_off_by_default_no_role_or_content_grants(self):
        admin = ROOT.parent / 'baseer_bwork_admin'
        source = (admin / 'models/retention.py').read_text(encoding='utf-8')
        self.assertIn('enabled = fields.Boolean(default=False', source)
        model_tree = ast.parse(source)
        for name in ('RetentionPolicy', 'RetentionWizard', 'RetentionRun', 'RetentionItem', 'RetentionAudit'):
            group = next(node for node in model_tree.body if isinstance(node, ast.ClassDef) and node.name == name)
            export = next(node for node in group.body if isinstance(node, ast.FunctionDef) and node.name == 'export_data')
            self.assertIn("self.check_access('read')", ast.get_source_segment(source, export))
        self.assertIn('access.check(model._name, operation, raise_exception=False)', source)
        self.assertIn('rule._compute_domain(model._name, operation)', source)
        self.assertIn("scope.append(('create_uid', '=', model.env.uid))", source)
        for field in ('candidate_bytes', 'logical_bytes', 'bytes'):
            self.assertIn('%s = fields.Char(' % field, source)
        native = ast.parse((admin / 'tests/test_retention.py').read_text(encoding='utf-8'))
        counts = {group.name: sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
                    for node in group.body) for group in native.body if isinstance(group, ast.ClassDef)}
        self.assertEqual(counts['BWorkRetentionCase'], 10)
        self.assertEqual(counts['BWorkRetentionHttpCase'], 2)
        workflow = (ROOT.parents[1] / '.github/workflows/test-bwork-retention.yml').read_text(encoding='utf-8')
        self.assertIn('-eq 12', workflow)
        for path in ('gallery_client.node.test.mjs', 'gallery_retention.node.test.mjs', 'baseer_bwork_admin/tests_contract'):
            self.assertIn(path, workflow)
        security = ET.parse(admin / 'security/retention_security.xml')
        self.assertFalse(security.findall(".//field[@name='users']"))
        self.assertFalse(security.findall(".//field[@name='implied_ids']"))
        protocol = (ROOT / 'models/retention.py').read_text(encoding='utf-8')
        self.assertIn("return bool(row and row[0] == '1')", protocol)
        self.assertIn('group and group in user.group_ids and manager in user.group_ids', protocol)
        self.assertNotIn('DELETE FROM baseer_bwork_message', protocol)


if __name__ == '__main__':
    unittest.main()
