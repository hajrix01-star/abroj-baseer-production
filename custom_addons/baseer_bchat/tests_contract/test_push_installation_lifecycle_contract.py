"""Source contract for safe BChat push-device reactivation after logout."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUSH_STATE = (ROOT.parents[1] / "android" / "bchat" / "app" / "src" / "main"
              / "java" / "com" / "baseer" / "freshchat" / "BChatPushState.java")


class PushInstallationLifecycleContractTests(unittest.TestCase):
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
