"""Cumulative source contracts for instant task push and private staff photos."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANDROID = (ROOT.parents[1] / 'android' / 'bchat' / 'app' / 'src' / 'main' / 'java'
           / 'com' / 'baseer' / 'freshchat' / 'OdooIdentityActivity.java')


class PushFastlaneAndAvatarContractTests(unittest.TestCase):
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
            'def _v2_member_avatar', '_require_bchat_permission', '_v2_current_member',
            "('room_id', '=', room.id)", "('active', '=', True)",
            'image_128', "raise ProtocolError('avatar_missing'",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        self.assertNotIn('/web/image', source)

        tree = ast.parse((ROOT / 'controllers' / 'api_v2.py').read_text(encoding='utf-8'))
        routes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'route']
        for path in ('/bchat/api/v2/rooms/<int:room_id>/members/<int:user_id>/avatar',
                     '/bchat/api/v2/profile/avatar'):
            route = next(node for node in routes if any(
                isinstance(arg, ast.Constant) and arg.value == path for arg in node.args))
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
