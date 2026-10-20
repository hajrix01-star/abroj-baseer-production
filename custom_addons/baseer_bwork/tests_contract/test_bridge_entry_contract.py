"""Regression contract for recovering an expired BWork WebView session."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = ROOT.parents[1] / "android" / "bwork-legacy" / "app" / "src" / "main" / "java" / "com" / "baseer" / "bwork" / "legacy" / "BWorkIdentityActivity.java"


class BridgeEntryContractTests(unittest.TestCase):
    def test_private_bridge_stays_hidden_before_login(self):
        source = (ROOT / "controllers" / "bridge.py").read_text(encoding="utf-8")
        server_test = (ROOT / "tests" / "test_bridge.py").read_text(encoding="utf-8")
        self.assertIn("auth='user'", source)
        self.assertIn("self.assertEqual(response.status_code, 404)", server_test)
        self.assertIn("self.assertNotIn('BWork', response.text)", server_test)

    def test_only_a_missing_private_bridge_recovers_to_login(self):
        source = ACTIVITY.read_text(encoding="utf-8")
        recovery = "if (!loggingOut && response.getStatusCode() == 404 && BRIDGE.equals(intendedUrl))"
        self.assertIn(recovery, source)
        start = source.index(recovery)
        end = source.index("if (response.getStatusCode() == 401", start)
        self.assertIn("recoverExpiredPrivateBridgeSession();", source[start:end])
        helper = "private boolean recoverExpiredPrivateBridgeSession()"
        helper_start = source.index(helper)
        helper_end = source.index("private void scheduleBridgeNavigationTimeout", helper_start)
        helper = source[helper_start:helper_end]
        self.assertIn("releaseWeb();", helper)
        self.assertIn("clearCookies", helper)
        self.assertNotIn("purgeHistory();", helper)
        self.assertIn("clearCookies", source[helper_start:helper_end])
        self.assertIn("openWeb(LOGIN);", source[helper_start:helper_end])

    def test_private_bootstrap_404_recovers_without_weakening_timeout_offline_fallback(self):
        source = ACTIVITY.read_text(encoding="utf-8")
        self.assertIn(
            'if (envelope.optInt("nonce", -1) == attempt && envelope.optInt("status", -1) == 404)',
            source,
        )
        timeout_start = source.index("private void scheduleBridgeNavigationTimeout")
        timeout_end = source.index("private boolean networkAvailable", timeout_start)
        timeout = source[timeout_start:timeout_end]
        self.assertIn("if (!offerOfflineHistory()) fail(R.string.auth_network_error);", timeout)
        self.assertNotIn("recoverExpiredPrivateBridgeSession", timeout)

    def test_sign_in_errors_name_the_qa_server_in_both_languages(self):
        arabic = (ROOT.parents[1] / "android" / "bwork-legacy" / "app" / "src" / "main" / "res" / "values-ar" / "strings.xml").read_text(encoding="utf-8")
        english = (ROOT.parents[1] / "android" / "bwork-legacy" / "app" / "src" / "main" / "res" / "values-en" / "strings.xml").read_text(encoding="utf-8")
        self.assertIn("خادم QA", arabic)
        self.assertIn("QA server", english)


if __name__ == "__main__":
    unittest.main()
