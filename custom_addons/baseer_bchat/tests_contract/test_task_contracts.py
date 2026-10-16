"""Offline checks for the bounded BChat task wire shape."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from uuid import uuid1, uuid4


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'bchat_task_contract_test_package'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for name in ('contracts', 'task_contracts'):
    spec = importlib.util.spec_from_file_location('%s.%s' % (PACKAGE, name), ROOT / ('%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
task = sys.modules['%s.task_contracts' % PACKAGE]


class BChatTaskContractTests(unittest.TestCase):
    def create_payload(self, **changed):
        value = {'api_version': 2, 'company_id': 3, 'room_id': None,
                 'client_uuid': str(uuid4()), 'title': 'Check stock',
                 'description': '', 'due_at': None, 'assignee_id': 5}
        value.update(changed)
        return value

    def transition_payload(self, **changed):
        value = {'api_version': 2, 'client_uuid': str(uuid4()),
                 'expected_revision': 1, 'action': 'start',
                 'assignee_id': None, 'reason': None}
        value.update(changed)
        return value

    def test_create_exact_schema_and_bounds(self):
        self.assertEqual(task.normalize_create(self.create_payload())['company_id'], 3)
        for change in ({'api_version': 1}, {'room_id': True}, {'company_id': 0},
                       {'client_uuid': str(uuid1())}, {'title': ' '},
                       {'title': 'ع' * 81}, {'description': 'x' * 4097},
                       {'due_at': 'tomorrow'}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(task.ProtocolError):
                task.normalize_create(self.create_payload(**change))
        self.assertEqual(task.normalize_create(self.create_payload(
            due_at='2026-10-09T13:14:15Z'))['due_at'], '2026-10-09 13:14:15')

    def test_transition_exact_actions_and_optional_notes(self):
        self.assertEqual(task.normalize_transition(self.transition_payload(reason='Started after stock check'))['action'], 'start')
        self.assertEqual(task.normalize_transition(self.transition_payload(
            action='rescue', assignee_id=8, reason='Both accounts left the room.'))['assignee_id'], 8)
        for change in ({'expected_revision': 0}, {'action': 'delete'},
                       {'action': 'done', 'assignee_id': 8},
                       {'action': 'reassign', 'assignee_id': None},
                       {'action': 'rescue', 'assignee_id': 8, 'reason': ' '},
                       {'reason': 'x' * 513}, {'unexpected': 'field'}):
            with self.subTest(change=change), self.assertRaises(task.ProtocolError):
                task.normalize_transition(self.transition_payload(**change))

    def test_digest_covers_exact_operation_and_fields(self):
        normalized = task.normalize_create(self.create_payload())
        baseline = task.digest('create', 0, normalized)
        self.assertEqual(baseline, task.digest('create', 0, normalized))
        self.assertNotEqual(baseline, task.digest('create', 9, normalized))
        self.assertNotEqual(baseline, task.digest('transition', 0, normalized))
        self.assertNotEqual(baseline, task.digest('create', 0, {**normalized, 'title': 'Changed'}))


if __name__ == '__main__':
    unittest.main()
