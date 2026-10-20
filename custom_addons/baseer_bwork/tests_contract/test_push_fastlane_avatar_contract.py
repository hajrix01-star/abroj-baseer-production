"""Cumulative source contracts for instant task push and private staff photos."""
import ast
from pathlib import Path
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANDROID = (ROOT.parents[1] / 'android' / 'bwork-legacy' / 'app' / 'src' / 'main' / 'java'
           / 'com' / 'baseer' / 'bwork' / 'legacy' / 'BWorkIdentityActivity.java')


class PushFastlaneAndAvatarContractTests(unittest.TestCase):
    def test_real_cursor_lock_fixture_has_deadlines_and_owned_cleanup(self):
        """Execute the authored harness body with strict fakes, not PostgreSQL proof."""
        tree = ast.parse((ROOT / 'tests/test_push_v2.py').read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == 'test_postgres_skip_locked_excludes_a_row_locked_by_another_worker')
        method.decorator_list = []

        class Query(str):
            def __new__(cls, code, *values):
                return str.__new__(cls, code % tuple(map(str, values)) if values else code)

            @staticmethod
            def identifier(name):
                if not name.startswith('bwork_push_lock_') or len(name) != len('bwork_push_lock_') + 32:
                    raise AssertionError('Expected one exact UUID fixture table')
                return Query('"' + name + '"')

        class Database:
            def __init__(self, fail=None):
                self.fail = fail
                self.cursors = []
                self.held_by = None
                self.created = self.dropped = False
                self.phases = []

            def cursor(self):
                cursor = Cursor(self, len(self.cursors))
                self.cursors.append(cursor)
                return cursor

        class Cursor:
            def __init__(self, db, identity):
                self.db, self.identity = db, identity
                self.deadlines = set()
                self.closed = False
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, *error):
                self.rollback()
                self.closed = True

            def execute(self, query):
                query = str(query)
                if query.startswith('SET LOCAL'):
                    self.deadlines.add(query)
                    return
                if self.deadlines != {"SET LOCAL lock_timeout = '2s'",
                                      "SET LOCAL statement_timeout = '15s'"}:
                    raise AssertionError('Every independent cursor must be bounded before SQL')
                if 'res_users' in query or 'TEMP ' in query:
                    raise AssertionError('Shared user/TEMP fixture cannot prove cross-worker ownership')
                if query.startswith('CREATE TABLE'):
                    if self.db.fail == 'create':
                        raise RuntimeError('injected create failure')
                    self.db.created = True
                elif query.startswith('INSERT INTO'):
                    if not self.db.created:
                        raise AssertionError('Insert requires owned fixture')
                elif query.startswith('SELECT'):
                    if self.db.fail == 'skip' and 'SKIP LOCKED' in query:
                        raise RuntimeError('injected worker failure')
                    if self.db.held_by is not None and self.db.held_by != self.identity:
                        if 'FOR UPDATE SKIP LOCKED' not in query:
                            raise AssertionError('Competing read must explicitly skip locks')
                        self.rows = []
                    else:
                        self.db.held_by = self.identity
                        self.rows = [(1,)]
                elif query.startswith('DROP TABLE'):
                    if not self.db.created or self.db.held_by is not None:
                        raise AssertionError('DROP requires owned fixture and released locks')
                    if not all(row.closed for row in self.db.cursors if row is not self):
                        raise AssertionError('Cleanup must follow all worker contexts')
                    self.db.dropped = True
                else:
                    raise AssertionError(query)

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return self.rows

            def commit(self):
                pass

            def rollback(self):
                if self.db.held_by == self.identity:
                    self.db.held_by = None

        def run(db, dbname='bwork_tasks_ci'):
            namespace = dict(
                SQL=Query, uuid4=lambda: types.SimpleNamespace(hex='a' * 32),
                sql_db=types.SimpleNamespace(db_connect=lambda name: db),
                _logger=types.SimpleNamespace(info=db.phases.append))
            exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                         'authored-push-lock-fixture', 'exec'), namespace)
            self.env = types.SimpleNamespace(cr=types.SimpleNamespace(dbname=dbname))
            namespace[method.name](self)

        db = Database()
        run(db)
        self.assertTrue(db.dropped)
        self.assertEqual(len(db.cursors), 5)
        self.assertTrue(all(row.closed for row in db.cursors))
        self.assertEqual([phase.rsplit(': ', 1)[-1] for phase in db.phases],
                         ['seed', 'held', 'skipped', 'released', 'visible', 'cleaned'])
        failed = Database(fail='create')
        with self.assertRaises(RuntimeError):
            run(failed)
        self.assertFalse(failed.dropped)
        interrupted = Database(fail='skip')
        with self.assertRaises(RuntimeError):
            run(interrupted)
        self.assertTrue(interrupted.dropped)
        foreign = Database()
        with self.assertRaises(AssertionError):
            run(foreign, dbname='not-the-disposable-ci-database')
        self.assertFalse(foreign.cursors)

    def test_task_push_is_durable_then_postcommit_and_room_visible(self):
        source = (ROOT / 'models' / 'push.py').read_text(encoding='utf-8')
        for required in (
            'ThreadPoolExecutor', 'threading.BoundedSemaphore',
            'def _schedule_fast_dispatch', 'self.env.cr.postcommit.add(submit)',
            'def _dispatch_event_ids', 'FOR UPDATE SKIP LOCKED',
            'cursor.commit()', 'def _fast_dispatch_events',
            '_FAST_DISPATCH_EXECUTOR.submit(_fast_dispatch_events, dbname, lane)',
            "('room_id', '=', task.room_id.id)", 'recipient_ids.discard(actor_id)',
            'queued._schedule_fast_dispatch(queued.ids)',
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_private_avatar_routes_recheck_membership_and_never_use_web_image(self):
        source = (ROOT / 'models' / 'avatar_service.py').read_text(encoding='utf-8')
        for required in (
            'def _v2_member_avatar', '_require_bwork_permission', '_v2_current_member',
            "('room_id', '=', room.id)", "('active', '=', True)",
            'image_128', 'def _v2_profile_avatar', 'user, self.env.company',
            "raise ProtocolError('avatar_missing'",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        self.assertNotIn('/web/image', source)

        tree = ast.parse((ROOT / 'controllers' / 'api_v2.py').read_text(encoding='utf-8'))
        routes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'route']
        for path in ('/bwork/api/v2/rooms/<int:room_id>/members/<int:user_id>/avatar',
                     '/bwork/api/v2/profile/avatar'):
            route = next(node for node in routes if any(
                isinstance(arg, ast.Constant) and arg.value == path for arg in ast.walk(node.args[0])))
            keywords = {keyword.arg: ast.literal_eval(keyword.value) for keyword in route.keywords}
            self.assertEqual(keywords['auth'], 'user')
            self.assertEqual(keywords['type'], 'http')
            self.assertTrue(keywords['csrf'])

    def test_android_uses_private_same_origin_avatar_reads_with_initial_fallback(self):
        source = ANDROID.read_text(encoding='utf-8')
        for required in (
            'V2_PROFILE_AVATAR', 'privateAvatarView', 'pumpPrivateAvatars',
            'private-avatar', 'credentials:\'same-origin\'', 'cache:\'no-store\'',
            'MAX_PRIVATE_AVATAR_BYTES', 'members/" + authorId + "/avatar',
            'showProfile()',
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)


if __name__ == '__main__':
    unittest.main()
