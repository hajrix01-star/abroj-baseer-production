"""Source contract for safe BWork push-device reactivation after logout."""
import ast
from pathlib import Path
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUSH_STATE = (ROOT.parents[1] / "android" / "bwork-legacy" / "app" / "src" / "main"
              / "java" / "com" / "baseer" / "bwork" / "legacy" / "BWorkPushState.java")


class PushInstallationLifecycleContractTests(unittest.TestCase):
    def test_reassignment_fixture_requires_new_recipient_without_actor_or_old_assignee(self):
        tree = ast.parse((ROOT / 'tests/test_push_v2.py').read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == 'test_token_moves_to_current_user_and_reassign_never_wakes_previous_assignee')
        assertions = [node for node in method.body if isinstance(node, ast.Expr)
                      and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                      and node.value.func.attr.startswith('assert')
                      and "events.mapped('recipient_id').ids" in ast.unparse(node)]
        self.assertEqual(len(assertions), 3)
        code = compile(ast.fix_missing_locations(ast.Module(body=assertions, type_ignores=[])),
                       'authored-reassignment-recipient-assertions', 'exec')
        self.creator = types.SimpleNamespace(id=5)
        self.assignee = types.SimpleNamespace(id=7)
        self.replacement = types.SimpleNamespace(id=9)
        def run(ids):
            events = types.SimpleNamespace(mapped=lambda name: types.SimpleNamespace(ids=ids))
            exec(code, {'self': self, 'events': events})
        run([9])
        for rejected in ([], [5, 9], [7, 9]):
            with self.subTest(recipients=rejected), self.assertRaises(AssertionError):
                run(rejected)

    def test_inactive_audit_fixtures_explicitly_include_retained_rows(self):
        tree = ast.parse((ROOT / 'tests/test_push_v2.py').read_text(encoding='utf-8'))
        for method_name, variable in (
                ('test_token_moves_to_current_user_and_reassign_never_wakes_previous_assignee', 'replaced'),
                ('test_unregister_and_private_models_do_not_grant_acl_access', 'device')):
            method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                          and node.name == method_name)
            lookup = next(node for node in method.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets))
            contexts = [node for node in ast.walk(lookup.value) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute) and node.func.attr == 'with_context']
            self.assertTrue(any(any(keyword.arg == 'active_test' and
                isinstance(keyword.value, ast.Constant) and keyword.value.value is False
                for keyword in context.keywords) for context in contexts))
            assertions = ast.unparse(method)
            self.assertIn('self.assertTrue(' + variable + ')', assertions)
            self.assertIn('self.assertFalse(' + variable + '.active)', assertions)
            self.assertIn(variable + '.inactive_reason', assertions)
            self.assertIn(variable + '.inactive_at', assertions)

    def test_legacy_revoke_fixtures_prove_outsider_denial_before_real_admin(self):
        source = (ROOT / 'tests/test_tasks_v2.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        helper = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == '_revoke_member')
        code = ast.unparse(helper)
        self.assertIn('with self.assertRaises(AccessError):', code)
        self.assertIn('membership.with_user(self.manager)', code)
        self.assertIn('membership.with_user(self.room_admin)', code)
        self.assertNotIn('.sudo(', code)
        self.assertEqual(source.count('self._revoke_member('), 3)

    def test_http_notification_uses_other_actor_and_preserves_no_self_wakeup(self):
        tree = ast.parse((ROOT / 'tests/test_tasks_v2.py').read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == 'test_task_options_create_list_and_csrf')
        code = ast.unparse(method)
        self.assertIn('self.assertFalse(event)', code)
        self.assertIn('self.assertNotEqual(assigner.id, user.id)', code)
        self.assertIn('.with_user(assigner)._v2_task_create(', code)
        self.assertIn("self.assertEqual(assigned['task']['creator_id'], assigner.id)", code)
        self.assertIn('self.assertTrue(event)', code)
        self.assertLess(code.index('self.assertFalse(event)'), code.index('.with_user(assigner)'))
        self.assertLess(code.index('self.assertTrue(event)'), code.index("notification = self.url_open("))

    def test_registration_and_logout_include_inactive_installations(self):
        source = (ROOT / "models" / "push.py").read_text(encoding="utf-8")
        register_start = source.index("def _register_verified")
        unregister_start = source.index("def _unregister_verified", register_start)
        register = source[register_start:unregister_start]
        unregister = source[unregister_start:]
        self.assertIn("with_context(active_test=False)", register)
        self.assertIn("('user_id', '=', user.id), ('installation_id', '=', installation_id)", register)
        self.assertIn("'active': True", register)
        self.assertIn("with_context(active_test=False)", unregister)

    def test_server_integration_suite_exercises_logout_then_reregistration(self):
        source = (ROOT / "tests" / "test_push_v2.py").read_text(encoding="utf-8")
        self.assertIn("test_registration_reactivates_the_same_device_after_logout", source)
        self.assertIn("_v2_push_unregister", source)
        self.assertIn("active_test=False", source)

    def test_client_preserves_a_verified_route_on_same_account_recheck(self):
        source = PUSH_STATE.read_text(encoding="utf-8")
        self.assertIn("if (account.key.equals(state.getString(SCOPE, null))) return;", source)
        self.assertIn(".remove(ACCOUNT).remove(REGISTERED_TOKEN)", source)
        self.assertIn("validUuid(installationId)", source)


if __name__ == "__main__":
    unittest.main()
