"""Executable modern payload/pagination contracts, without an Odoo runtime."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'bwork_task_contract_package'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for name in ('contracts', 'task_contracts', 'work_task_contracts'):
    spec = importlib.util.spec_from_file_location(PACKAGE + '.' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
wire = sys.modules[PACKAGE + '.work_task_contracts']


class WorkTaskContractCase(unittest.TestCase):
    def create(self, **changes):
        payload = dict(api_version=2, work_tasks_version=1, company_id=3, room_id=None,
            client_uuid=str(uuid4()), title='Repair AC', description='', due_at=None,
            reminder_at=None, assignee_id=9)
        payload.update(changes)
        return payload

    def transition(self, **changes):
        payload = dict(api_version=2, work_tasks_version=1, company_id=3,
            client_uuid=str(uuid4()), expected_revision=1, action='done', assignee_id=None, reason=None)
        payload.update(changes)
        return payload

    def test_versions_schema_utf8_and_standalone(self):
        self.assertEqual(wire.normalize_create(self.create())['company_id'], 3)
        for change in ({'work_tasks_version': True}, {'work_tasks_version': 2},
                       {'api_version': 1}, {'room_id': 3}, {'extra': 1},
                       {'title': 'ع' * 81}, {'company_id': True}, {'description': '\x00'}):
            with self.subTest(change=change), self.assertRaises(wire.ProtocolError):
                wire.normalize_create(self.create(**change))

    def test_due_reminder_order_and_past_is_deterministic(self):
        payload = self.create(due_at='2020-10-19T10:00:00Z', reminder_at='2020-10-19T09:00:00Z')
        self.assertEqual(wire.normalize_create(payload)['reminder_at'], '2020-10-19 09:00:00')
        for change in ({'reminder_at': '2020-10-19T09:00:00Z'},
                       {'due_at': '2020-10-19T09:00:00Z', 'reminder_at': '2020-10-19T10:00:00Z'},
                       {'due_at': '2020-02-30T09:00:00Z'}, {'due_at': '2020-10-19T09:00:00+01:00'}):
            with self.subTest(change=change), self.assertRaises(wire.ProtocolError):
                wire.normalize_create(self.create(**change))

    def test_actions_no_rescue_exact_company_and_notes(self):
        self.assertEqual(wire.normalize_transition(self.transition())['action'], 'done')
        for change in ({'action': 'rescue'}, {'company_id': 0}, {'reason': 'ع' * 257},
                       {'assignee_id': 3}, {'expected_revision': True}, {'extra': 1},
                       {'action': 'reassign', 'assignee_id': None}):
            with self.subTest(change=change), self.assertRaises(wire.ProtocolError):
                wire.normalize_transition(self.transition(**change))

    def test_digest_separates_protocol_company_and_immutable_expected_revision(self):
        values = wire.normalize_transition(self.transition())
        self.assertNotEqual(wire.digest('transition', 2, values), wire.legacy.digest('transition', 2, values))
        self.assertNotEqual(wire.digest('transition', 2, values),
                            wire.digest('transition', 2, dict(values, expected_revision=2)))
        self.assertNotEqual(wire.digest('transition', 2, values),
                            wire.digest('transition', 2, dict(values, company_id=4)))

    def test_byte_adaptive_page_never_skips_tail_or_false_empty(self):
        rows = [{'id': 100 - i, 'description': 'x' * 11000} for i in range(30)]
        result = wire.page({'api_version': 2, 'work_tasks_version': 1}, rows, True)
        self.assertGreater(len(result['tasks']), 0)
        self.assertLess(len(result['tasks']), 30)
        self.assertEqual(result['next_before_id'], result['tasks'][-1]['id'])
        self.assertLessEqual(wire.wire_size(result), wire.LIST_BYTES)
        next_rows = [row for row in rows if row['id'] < result['next_before_id']]
        self.assertEqual(next_rows[0], rows[len(result['tasks'])])
        self.assertIsNone(wire.page({}, [{'id': 1}], False)['next_before_id'])
        with self.assertRaises(wire.ProtocolError):
            wire.page({}, [{'id': 1, 'description': 'x' * wire.TASK_BYTES}], False)

    def test_1000_company_options_capacity_and_assignee_capacity(self):
        options = {'companies': [{'id': i + 1, 'name': 'ع' * 128} for i in range(1000)]}
        self.assertIs(wire.bounded(options, wire.OPTIONS_BYTES), options)
        assignees = {'assignees': [{'id': i + 1, 'name': 'ع' * 128} for i in range(50)]}
        self.assertIs(wire.bounded(assignees, wire.ASSIGNEES_BYTES), assignees)

    def test_routes_registered_authenticated_csrf_bounded(self):
        tree = ast.parse((ROOT / 'controllers/work_task_api.py').read_text(encoding='utf-8'))
        routes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'route']
        self.assertEqual(len(routes), 6)
        for route in routes:
            options = {k.arg: ast.literal_eval(k.value) for k in route.keywords}
            self.assertEqual(options['auth'], 'user')
            self.assertTrue(options['csrf'])
            if options['methods'] == ['POST']:
                self.assertEqual(options['max_content_length'], 65536)
        self.assertIn('from . import work_task_api', (ROOT / 'controllers/__init__.py').read_text())


if __name__ == '__main__':
    unittest.main()
