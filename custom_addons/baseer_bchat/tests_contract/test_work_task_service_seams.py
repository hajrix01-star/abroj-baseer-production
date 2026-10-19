"""Execute actual production method bodies with bounded fakes, not ORM proof."""
import ast
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
import types
import unittest

from test_work_task_contracts import wire

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 19, 10, 0, 0)


def production_method(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    method.decorator_list = []
    namespace = dict(fields=types.SimpleNamespace(Datetime=types.SimpleNamespace(now=lambda: NOW)),
                     wire=wire, _TASK_SERVICE_TOKEN=object(), _PUSH_TOKEN=object(),
                     AccessError=PermissionError, ProtocolError=wire.ProtocolError)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                 str(ROOT / path), 'exec'), namespace)
    return namespace[name]


schedule = production_method('models/work_task_service.py', '_work_task_schedule_reminders')
allowed = production_method('models/push.py', '_event_recipient_still_allowed')


class Record(types.SimpleNamespace):
    def invalidate_recordset(self):
        pass

    def _write_verified(self, values, token):
        self.__dict__.update(values)


class Cursor:
    def __init__(self, fixture):
        self.fixture = fixture
        self.result = None

    def execute(self, sql, args):
        self.fixture.order.append(('task', args[0]))
        self.result = None if args[0] in self.fixture.busy else (args[0],)
        if 'SKIP LOCKED' not in sql and 'FOR SHARE' not in sql:
            raise AssertionError('Expected source task row lock')

    def fetchone(self):
        return self.result

    def savepoint(self):
        return nullcontext()


class Fixture:
    def __init__(self, count=1):
        self.rows = [Record(id=i + 1, room_id=Record(id=3), company_id=Record(id=5),
            assignee_id=Record(id=7), reminder_at=NOW - timedelta(minutes=1),
            reminder_emitted_at=None, state='new', revision=1) for i in range(count)]
        self.changes, self.pushes, self.order, self.busy, self.fast = [], [], [], set(), []
        self.eligible = True
        self.fail_queue = False
        self.env = types.SimpleNamespace(cr=Cursor(self))
        self.env = Env(self)

    def _work_task_can_execute(self, *args):
        self.order.append(('eligibility', args))
        return self.eligible

    def _task_member(self, *args):
        return Record(id=11)

    def _change_publish(self, recipients, kind, **values):
        self.changes.append((recipients, kind, values))

    def _work_task_reminder_candidates(self, now):
        return [row for row in self.rows if row.state in ('new', 'in_progress')
                and row.reminder_at and row.reminder_at <= now and not row.reminder_emitted_at][:50]

    def run(self):
        return schedule(self)


class Env:
    def __init__(self, fixture):
        self.fixture = fixture
        self.cr = Cursor(fixture)

    def __getitem__(self, name):
        fixture = self.fixture
        if name == 'baseer.bchat.task':
            return Model(search=lambda domain, order, limit: [row for row in fixture.rows
                if row.state in ('new', 'in_progress') and row.reminder_at
                and row.reminder_at <= NOW and not row.reminder_emitted_at][:limit])
        if name == 'baseer.bchat.room':
            return Model(_lock_for_read=lambda room_id: fixture.order.append(('room', room_id)))
        if name == 'baseer.bchat.push.device':
            return Model(search=lambda *args, **kwargs: [Record(id=13)])
        if name == 'baseer.bchat.membership':
            return Model(search=lambda *args, **kwargs: True)
        if name == 'baseer.bchat.push.event':
            def queue(rows, token):
                if fixture.fail_queue:
                    raise RuntimeError('database queue unavailable')
                fixture.pushes.extend(rows)
                return Record(ids=[17], _schedule_fast_dispatch=lambda ids: fixture.fast.extend(ids))
            return Model(_queue_verified=queue)
        raise AssertionError(name)


class Model(types.SimpleNamespace):
    def sudo(self):
        return self


class WorkTaskProductionSeamCase(unittest.TestCase):
    def test_actual_assignee_picker_requires_manage_before_directory_access(self):
        pick = production_method('models/work_task_service.py', '_work_task_assignees')
        checked = []
        def scope(company_id, manage=False):
            checked.append((company_id, manage))
            if manage:
                raise PermissionError('task_manage required')
            raise AssertionError('View-only must not reach an assignee lookup')
        fixture = Record(_work_task_scope=scope)
        with self.assertRaises(PermissionError):
            pick(fixture, 3)
        self.assertEqual(checked, [(3, True)])

    def test_actual_serializer_fits_maximal_escaped_task_without_losing_text(self):
        serialize = production_method('models/work_task_service.py', '_work_task_data')
        label = production_method('models/work_task_service.py', '_work_task_label')
        name = '\U0001f600' * 64
        actor = Record(id=2147483647, name=name)
        task = Record(company_id=actor, creator_id=actor, assignee_id=actor,
            started_at=NOW, done_at=NOW, cancelled_at=NOW, done_by_id=actor,
            completion_note='"' * 512, reminder_at=NOW, reminder_emitted_at=NOW,
            state='in_progress', origin_api='work_tasks_v1')
        stamp = '2026-10-19T10:00:00Z'
        base = dict(id=2147483647, company_id=2147483647, room_id=2147483647,
            title='"' * 160, description='"' * 4096, state='in_progress',
            creator_id=2147483647, creator_name=name, assignee_id=2147483647, assignee_name=name,
            due_at=stamp, created_at=stamp, updated_at=stamp, revision=2147483647,
            last_actor_id=2147483647, last_changed_at=stamp, last_note='"' * 512)
        fixture = Record(_task_data=lambda row: dict(base), _task_label=lambda value: value,
            _task_stamp=lambda value: stamp, _work_task_actions=lambda row: ['start', 'done', 'cancel', 'reassign'])
        fixture._work_task_label = lambda value: label(fixture, value)
        result = serialize(fixture, task)
        self.assertLessEqual(wire.wire_size(result), wire.TASK_BYTES)
        self.assertEqual(result['description'], base['description'])
        self.assertEqual(result['last_note'], base['last_note'])
        self.assertEqual(result['completion_note'], task.completion_note)

    def test_scheduler_bounded_once_audience_and_room_before_task_lock(self):
        fixture = Fixture(60)
        self.assertEqual(fixture.run(), 50)
        self.assertEqual(len(fixture.changes), 50)
        self.assertEqual(len(fixture.pushes), 50)
        self.assertEqual(fixture.order[:2], [('room', 3), ('task', 1)])
        self.assertTrue(all(change[0] == [7] for change in fixture.changes))
        self.assertTrue(all(row['recipient_id'] == 7 and row['event_kind'] == 'reminder'
                            for row in fixture.pushes))
        self.assertEqual(fixture.run(), 10)
        self.assertEqual(fixture.run(), 0)

    def test_busy_and_revoked_candidate_cannot_queue_or_mark(self):
        fixture = Fixture()
        fixture.busy.add(1)
        self.assertEqual(fixture.run(), 0)
        self.assertFalse(fixture.changes)
        fixture.busy.clear()
        fixture.eligible = False
        self.assertEqual(fixture.run(), 0)
        self.assertFalse(fixture.rows[0].reminder_emitted_at)
        self.assertFalse(fixture.pushes)

    def test_failed_queue_does_not_set_marker_or_schedule_delivery(self):
        fixture = Fixture()
        fixture.fail_queue = True
        with self.assertRaises(RuntimeError):
            fixture.run()
        self.assertFalse(fixture.rows[0].reminder_emitted_at)
        self.assertFalse(fixture.fast)
        # Real change-row/savepoint rollback is covered by the ORM test, not
        # fabricated here by a fake PostgreSQL transaction implementation.

    def test_delivery_rechecks_exact_assignee_revision_terminal_rights_company(self):
        fixture = Fixture()
        company = fixture.rows[0].company_id
        rights = dict(task_view=True, task_manage=True)
        user = Record(id=7, active=True, company_ids=[company], _is_internal=lambda: True,
                      _bchat_effective_permissions=lambda: rights)
        task = fixture.rows[0]
        task.reminder_emitted_at = NOW
        event = Record(recipient_id=user, device_id=Record(active=True), message_id=None,
                       task_id=task, company_id=company, event_kind='reminder', task_revision=1)
        self.assertTrue(allowed(fixture, event))
        for field, rejected, original in (
                ('assignee_id', Record(id=8), task.assignee_id),
                ('state', 'done', 'new'), ('state', 'cancelled', 'new'),
                ('revision', 2, 1), ('reminder_emitted_at', None, NOW)):
            setattr(task, field, rejected)
            self.assertFalse(allowed(fixture, event), field)
            setattr(task, field, original)
        rights['task_manage'] = False
        self.assertFalse(allowed(fixture, event))
        rights['task_manage'] = True
        rights['task_view'] = False
        self.assertFalse(allowed(fixture, event))
        rights['task_view'] = True
        user.company_ids = []
        self.assertFalse(allowed(fixture, event))

    def test_replay_precedes_revision_and_terminal_checks_in_actual_body(self):
        transition = production_method('models/work_task_service.py', '_work_task_transition')
        task = Record(id=9, revision=8, state='done')
        event = Record(task_id=Record(id=9), payload_digest='expected', result_revision=2)
        receipt = {'task': {'id': 9, 'state': 'done'}, 'operation_revision': 2}
        fixture = Record(
            _work_task_scope=lambda *args, **kwargs: (Record(id=7), [3]),
            _work_task_locked=lambda *args, **kwargs: task,
            _work_task_receipt=lambda *args: receipt,
            env=Record(cr=Record(savepoint=lambda: nullcontext())))
        class ReplayEnv:
            cr = fixture.env.cr
            def __getitem__(self, name):
                return Model(search=lambda *args, **kwargs: event)
        fixture.env = ReplayEnv()
        payload = dict(api_version=2, work_tasks_version=1, company_id=3,
            client_uuid='0faba7c7-f713-4794-b7d9-17c6b46681ed', expected_revision=1,
            action='done', assignee_id=None, reason=None)
        original = wire.digest
        wire.digest = lambda *args: 'expected'
        try:
            self.assertIs(transition(fixture, 9, payload), receipt)
        finally:
            wire.digest = original


if __name__ == '__main__':
    unittest.main()
