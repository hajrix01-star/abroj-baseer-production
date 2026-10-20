"""Locally executable contracts; these deliberately do not claim ORM evidence."""
import ast
import csv
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import unicodedata
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
ADDON = ROOT / 'custom_addons/baseer_bwork_admin'
spec = importlib.util.spec_from_file_location('bwork_admin_pure_contract', ADDON / 'contracts.py')
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)


def source_function(class_name, method_name):
    tree = ast.parse((ROOT / 'custom_addons/baseer_bchat/models/push.py').read_text(encoding='utf-8'))
    group = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == class_name)
    function = next(item for item in group.body if isinstance(item, ast.FunctionDef) and item.name == method_name)
    function.decorator_list = []
    namespace = {'re': re, 'unicodedata': unicodedata}
    # Reuse the actual sanitization/error implementation, not a parallel sender.
    helpers = [item for item in tree.body if getattr(item, 'name', None) in ('_notification_text', '_PushTransportError')]
    exec(compile(ast.Module(body=helpers + [function], type_ignores=[]), '<production-push-method>', 'exec'), namespace)
    return namespace[method_name]


class BWorkAdminPureContract(unittest.TestCase):
    def test_strict_company_scope_and_batch_limit(self):
        self.assertEqual(wire.company_ids([9, 2]), [2, 9])
        for value in (None, [], [True], [0], [-1], [1, 1], list(range(1, 12)), '1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                wire.company_ids(value)

    def test_page_bounds_are_not_silent_truncation(self):
        self.assertEqual(wire.pagination(), (0, 80))
        self.assertEqual(wire.pagination(100000, 200), (100000, 200))
        for args in ((True, 80), (0, True), (0, 201), (-1, 80), (100001, 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                wire.pagination(*args)

    def test_integer_warning_disabled_and_exact_boundary(self):
        self.assertEqual(wire.warning_status(999999999, 0), 'disabled')
        self.assertEqual(wire.warning_status(1048575, 1), 'below')
        self.assertEqual(wire.warning_status(1048576, 1), 'reached')
        for value in (True, 1.5, -1, wire.MAX_WARNING_MIB + 1, '1'):
            with self.assertRaises(ValueError):
                wire.warning(value)

    def test_decimal2_english_digits_without_float_rounding(self):
        self.assertEqual(wire.mib(1048576), '1.00')
        self.assertEqual(wire.mib(1048576 * 1024 + 524288), '1024.50')
        self.assertEqual(wire.mib(1048576 * 999999999), '999999999.00')
        self.assertRegex(wire.mib(123456789), r'^[0-9]+\.[0-9]{2}$')

    def test_response_byte_limit_includes_unicode(self):
        self.assertEqual(wire.bounded_response({'count': 0}), {'count': 0})
        with self.assertRaises(ValueError):
            wire.bounded_response({'text': 'ع' * wire.MAX_RESPONSE_BYTES})

    def test_addon_has_one_dependency_no_hooks_seeds_or_source_acl(self):
        manifest = ast.literal_eval((ADDON / '__manifest__.py').read_text(encoding='utf-8'))
        self.assertEqual(manifest['depends'], ['baseer_bchat'])
        self.assertFalse(manifest['auto_install'])
        self.assertFalse(any('hook' in key for key in manifest))
        with (ADDON / 'security/ir.model.access.csv').open(encoding='utf-8') as source:
            acls = list(csv.DictReader(source))
        self.assertEqual({row['model_id:id'] for row in acls}, {'model_baseer_bwork_admin_console', 'model_baseer_bwork_admin_policy'})
        self.assertTrue(all(row['perm_unlink'] == '0' for row in acls))
        self.assertEqual([entry for entry in manifest['data'] if entry.startswith('data/')], ['data/retention_cron.xml'])
        retention = (ADDON / 'models/retention.py').read_text(encoding='utf-8')
        self.assertIn('enabled = fields.Boolean(default=False', retention)
        self.assertIn('_retention_ready(lock=True)', retention)
        security = ET.parse(ADDON / 'security/retention_security.xml')
        self.assertFalse(security.findall(".//field[@name='users']"))
        self.assertFalse(security.findall(".//field[@name='implied_ids']"))
        with (ADDON / 'security/retention_access.csv').open(encoding='utf-8') as source:
            new_acls = list(csv.DictReader(source))
        self.assertTrue(all(row['perm_unlink'] == '0' for row in new_acls if 'wizard' not in row['model_id:id']))
        self.assertTrue(all(row['perm_write'] == row['perm_create'] == '0' for row in new_acls
                            if row['model_id:id'].endswith(('_audit', '_item'))))

    def test_native_metadata_forms_are_readonly_and_no_custom_framework(self):
        tree = ET.parse(ADDON / 'views/admin_views.xml')
        for name in ('room_form', 'member_form'):
            form = tree.find("./record[@id='%s']/field[@name='arch']/form" % name)
            self.assertEqual(form.attrib['create'], '0')
            self.assertEqual(form.attrib['edit'], '0')
            self.assertEqual(form.attrib['delete'], '0')
        self.assertFalse(list(ADDON.rglob('*.js')))
        runtime = (ADDON / 'models/administration.py').read_text(encoding='utf-8')
        group = next(item for item in ast.parse(runtime).body if isinstance(item, ast.ClassDef) and item.name == 'BWorkAdminConsole')
        cleanup = next(item for item in group.body if isinstance(item, ast.FunctionDef) and item.name == '_transient_clean_rows_older_than')
        code = ast.get_source_segment(runtime, cleanup)
        self.assertIn('FROM baseer_bwork_admin_console', code)
        self.assertIn('max(seconds, 300)', code)
        self.assertIn('GC_UNLINK_LIMIT', code)
        self.assertIn('self.env.cr.now()', code)
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                             and node.func.attr == 'search' for node in ast.walk(cleanup)))
        self.assertNotIn('DELETE FROM', code)

    def test_bilingual_catalogs_cover_native_view_and_runtime_labels(self):
        runtime = ast.parse((ADDON / 'models/administration.py').read_text(encoding='utf-8'))
        labels = {call.args[0].value for call in ast.walk(runtime)
                  if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                  and call.func.attr == '_' and call.args and isinstance(call.args[0], ast.Constant)}
        xml = ET.parse(ADDON / 'views/admin_views.xml')
        labels |= {item.attrib['string'] for item in xml.iter() if 'string' in item.attrib}
        labels |= {item.text.strip() for item in xml.iter('p')}
        for language in ('ar', 'ar_001'):
            # The catalog intentionally uses simple one-line message entries;
            # parse with stdlib rather than installing Babel just for local QA.
            text = (ADDON / 'i18n' / (language + '.po')).read_text(encoding='utf-8')
            entries = {}
            key = None
            for line in text.splitlines():
                if line.startswith('msgid '):
                    key = ast.literal_eval(line[6:])
                elif line.startswith('msgstr ') and key:
                    entries[key] = ast.literal_eval(line[7:])
            self.assertFalse(labels - entries.keys(), '%s missing labels' % language)
            self.assertTrue(all(entries[label] for label in labels))
            self.assertFalse(any(any('٠' <= char <= '٩' for char in translated) for translated in entries.values()))

    def test_runtime_count_matches_all_exactly_selected_classes(self):
        sources = [(ADDON / 'tests/test_admin.py', {'BWorkAdminCase', 'BWorkAdminHttpCase'}),
                   (ROOT / 'custom_addons/baseer_bchat/tests/test_bwork_push_privacy.py', {'BWorkPushPrivacyCase'})]
        count = sum(1 for path, names in sources for group in ast.parse(path.read_text(encoding='utf-8')).body
                    if isinstance(group, ast.ClassDef) and group.name in names
                    for method in group.body if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'))
        self.assertEqual(count, 17)

    def test_actual_production_fcm_method_omits_every_preview_for_bwork(self):
        send = source_function('BChatPushEvent', '_fcm_send')
        post = Mock(return_value=SimpleNamespace(status_code=200))
        device = SimpleNamespace(account_key='fixture-account', fcm_token='fixture-token', client_kind='bwork')
        method_self = SimpleNamespace(_fcm_access_token=lambda config: 'fixture-access')
        with patch.dict(sys.modules, {'requests': SimpleNamespace(post=post)}):
            for text, media in (('PRIVATE TEXT', False), ('', True)):
                event = SimpleNamespace(id=7, device_id=device,
                    message_id=SimpleNamespace(text=text, media_id=media, author_user_id=SimpleNamespace(name='PRIVATE NAME')))
                send(method_self, event, {'project_id': 'fixture-project'})
                body = post.call_args.kwargs['json']['message']
                self.assertEqual(body['data'], {'account_key': 'fixture-account', 'kind': 'chat', 'event_id': '7'})
                self.assertNotIn('notification', body)
        self.assertEqual(post.call_count, 2)

    def test_actual_production_sender_preserves_explicit_legacy_contract(self):
        send = source_function('BChatPushEvent', '_fcm_send')
        post = Mock(return_value=SimpleNamespace(status_code=200))
        event = SimpleNamespace(id=8, device_id=SimpleNamespace(account_key='legacy', fcm_token='fixture', client_kind='legacy'),
            message_id=SimpleNamespace(text='Legacy preview', media_id=False, author_user_id=SimpleNamespace(name='Legacy name')))
        with patch.dict(sys.modules, {'requests': SimpleNamespace(post=post)}):
            send(SimpleNamespace(_fcm_access_token=lambda config: 'fixture'), event, {'project_id': 'fixture'})
        self.assertEqual(post.call_args.kwargs['json']['message']['data']['message_preview'], 'Legacy preview')

    def test_isolated_workflow_keeps_pinned_images_and_exact_runtime_count(self):
        workflow = (ROOT / '.github/workflows/test-bwork-admin.yml').read_text(encoding='utf-8')
        self.assertIn('postgres@sha256:f1c3376c', workflow)
        self.assertIn('odoo@sha256:f99ffac9', workflow)
        self.assertIn('BWorkPushPrivacyCase', workflow)
        self.assertIn('-eq 17', workflow)
        self.assertIn('0 failed, 0 error(s)', workflow)


if __name__ == '__main__':
    unittest.main()
