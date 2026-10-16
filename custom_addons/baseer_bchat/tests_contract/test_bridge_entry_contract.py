"""Regression contract for recovering an expired BChat WebView session."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = ROOT.parents[1] / "android" / "bchat" / "app" / "src" / "main" / "java" / "com" / "baseer" / "freshchat" / "OdooIdentityActivity.java"


class BridgeEntryContractTests(unittest.TestCase):
    def test_private_bridge_stays_hidden_before_login(self):
        source = (ROOT / "controllers" / "bridge.py").read_text(encoding="utf-8")
        server_test = (ROOT / "tests" / "test_bridge.py").read_text(encoding="utf-8")
        self.assertIn("auth='user'", source)
        self.assertIn("self.assertEqual(response.status_code, 404)", server_test)
        self.assertIn("self.assertNotIn('BChat', response.text)", server_test)

    def test_only_a_missing_private_bridge_recovers_to_login(self):
        source = ACTIVITY.read_text(encoding="utf-8")
        recovery = "if (!loggingOut && response.getStatusCode() == 404 && BRIDGE.equals(intendedUrl))"
        self.assertIn(recovery, source)
        start = source.index(recovery)
        end = source.index("if (response.getStatusCode() == 401", start)
        self.assertIn("purgeHistory();", source[start:end])
        self.assertIn("clearCookies", source[start:end])
        self.assertIn("openWeb(LOGIN);", source[start:end])

    def test_sign_in_errors_name_the_qa_server_in_both_languages(self):
        arabic = (ROOT.parents[1] / "android" / "bchat" / "app" / "src" / "main" / "res" / "values-ar" / "strings.xml").read_text(encoding="utf-8")
        english = (ROOT.parents[1] / "android" / "bchat" / "app" / "src" / "main" / "res" / "values-en" / "strings.xml").read_text(encoding="utf-8")
        self.assertIn("خادم QA", arabic)
        self.assertIn("QA server", english)


if __name__ == "__main__":
    unittest.main()
