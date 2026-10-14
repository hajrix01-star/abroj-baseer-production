"""Fast pure-contract checks for the group wire format."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'bchat_group_contract_test_package'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for name in ('contracts', 'group_contracts'):
    spec = importlib.util.spec_from_file_location('%s.%s' % (PACKAGE, name), ROOT / ('%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
group = sys.modules['%s.group_contracts' % PACKAGE]
ProtocolError = group.ProtocolError
create_digest = group.create_digest
normalize_change = group.normalize_change
normalize_create = group.normalize_create


class GroupContractCase(unittest.TestCase):
    def test_room_metadata_is_one_bounded_sql_shape(self):
        source = ast.parse((ROOT / 'models' / 'v2_service.py').read_text(encoding='utf-8'))
        function = next(node for cls in source.body if isinstance(cls, ast.ClassDef)
                        for node in cls.body if isinstance(node, ast.FunctionDef)
                        and node.name == '_v2_room_rows')
        method_calls = [node.func.attr for node in ast.walk(function)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertEqual(method_calls.count('execute'), 1)
        self.assertNotIn('search', method_calls)
        self.assertNotIn('search_count', method_calls)
        self.assertIn('LATERAL', ast.get_source_segment(
            (ROOT / 'models' / 'v2_service.py').read_text(encoding='utf-8'), function))

    def test_create_is_canonical_and_stable(self):
        payload = {'api_version': 2, 'client_uuid': str(uuid4()),
                   'company_id': 4, 'name': 'Purchasing', 'member_user_ids': [8, 3]}
        one = normalize_create(payload)
        two = normalize_create({**payload, 'member_user_ids': [3, 8]})
        self.assertEqual(one, two)
        self.assertEqual(create_digest(one), create_digest(two))

    def test_reject_cross_field_and_duplicate_members(self):
        payload = {'api_version': 2, 'client_uuid': str(uuid4()),
                   'company_id': 4, 'name': 'Purchasing', 'member_user_ids': [3, 3]}
        with self.assertRaises(ProtocolError):
            normalize_create(payload)
        with self.assertRaises(ProtocolError):
            normalize_create({**payload, 'member_user_ids': [3], 'is_admin': True})
        self.assertEqual(len(normalize_create({**payload,
            'member_user_ids': list(range(1, 50))})['member_user_ids']), 49)
        with self.assertRaises(ProtocolError):
            normalize_create({**payload, 'member_user_ids': list(range(1, 51))})

    def test_change_shapes_are_exact(self):
        self.assertEqual(normalize_change({'api_version': 2, 'action': 'rename',
                                           'name': 'New name'})['name'], 'New name')
        for payload in ({'api_version': 2, 'action': 'leave', 'user_id': 5},
                        {'api_version': 2, 'action': 'promote_admin'},
                        {'api_version': 2, 'action': 'rename', 'name': '\n'}):
            with self.assertRaises(ProtocolError):
                normalize_change(payload)
