"""The real CI race probe stays separate, bounded, required and fail-closed."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / 'tests/work_task_reminder_concurrency_probe.py'
WORKFLOW = ROOT.parents[1] / '.github/workflows/test-bwork-tasks.yml'


class WorkTaskReminderProbeContractCase(unittest.TestCase):
    def test_foreign_database_refused_before_any_connection(self):
        tree = ast.parse(PROBE.read_text(encoding='utf-8'))
        method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
        module = ast.Module(body=[method], type_ignores=[])
        namespace = {}
        exec(compile(ast.fix_missing_locations(module), str(PROBE), 'exec'), namespace)
        class Foreign:
            class cr:
                dbname = 'not_the_disposable_database'
        with self.assertRaisesRegex(RuntimeError, 'Refusing committed reminder probe'):
            namespace['run'](Foreign())

    def test_every_real_cursor_bounded_and_cleanup_precedes_success(self):
        source = PROBE.read_text(encoding='utf-8')
        tree = ast.parse(source)
        cursors = [node for node in ast.walk(tree) if isinstance(node, ast.With)
                   and isinstance(node.items[0].context_expr, ast.Call)
                   and isinstance(node.items[0].context_expr.func, ast.Attribute)
                   and node.items[0].context_expr.func.attr == 'cursor']
        self.assertEqual(len(cursors), 5)
        for cursor in cursors:
            self.assertEqual(ast.unparse(cursor.body[0]), '_bounded(' + cursor.items[0].optional_vars.id + ')')
        self.assertIn("SET LOCAL lock_timeout = '2s'", source)
        self.assertIn("SET LOCAL statement_timeout = '15s'", source)
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
        self.assertIsInstance(run.body[-2], ast.Try)
        self.assertTrue(run.body[-2].finalbody)
        self.assertEqual(ast.unparse(run.body[-1]), "print('BWORK_TASK_REMINDER_CONCURRENCY=PASS')")
        for identity in ('(marker, user_id)', "browse(user_id).login, marker", 'cleanup_cr.rowcount, 1'):
            self.assertIn(identity, source)

    def test_production_claim_assertions_preserved_without_mock(self):
        source = PROBE.read_text(encoding='utf-8')
        self.assertEqual(source.count("worker['baseer.bwork.task']._cron_work_task_reminders(), 0"), 2)
        self.assertEqual(source.count("worker['baseer.bwork.task']._cron_work_task_reminders(), 1"), 1)
        for required in ('FOR UPDATE', 'check.assertIsNone(worker_cr.fetchone()[0])',
                         'check.assertIsNotNone(worker_cr.fetchone()[0])',
                         'check.assertEqual(worker_cr.fetchone()[0], 0)',
                         'check.assertEqual(worker_cr.fetchone()[0], 1)',
                         'seed_cr.commit()', 'locker.rollback()', 'worker_cr.commit()'):
            self.assertIn(required, source)
        self.assertNotIn('mock', '\n'.join(source.splitlines()[6:]))
        self.assertNotIn('work_task_reminder_concurrency_probe', (ROOT / 'tests/__init__.py').read_text())

    def test_workflow_requires_41_cases_then_real_probe_and_both_logs(self):
        source = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('" -eq 41', source)
        self.assertIn('41', source)
        self.assertLess(source.index("grep -F '0 failed, 0 error(s)'"),
                        source.index('Genuine reminder lock and once-only emission'))
        for required in ('from odoo.addons.baseer_bwork.tests.work_task_reminder_concurrency_probe import run',
                         'run(env)', "grep -Fx 'BWORK_TASK_REMINDER_CONCURRENCY=PASS'",
                         'bwork-tasks-runtime.log', 'bwork-tasks-concurrency.log', 'timeout-minutes: 20'):
            self.assertIn(required, source)


if __name__ == '__main__':
    unittest.main()
