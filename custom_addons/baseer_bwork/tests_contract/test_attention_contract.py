"""Offline contract checks for the per-user BWork attention center.

These are source-shape checks only. Odoo access, company isolation and the
membership query remain covered by the server integration suite before QA.
"""
from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AttentionContractTests(unittest.TestCase):
    def test_attention_contract_is_bounded_and_personal(self):
        source = (ROOT / "models" / "attention_service.py").read_text(encoding="utf-8")
        for required in (
            "def _v2_attention", "_require_any_bwork_permission", "user.company_ids.ids",
            "joined_after_message_id", "assignee_id", "badge_count", "min(total, 50)",
            "JOIN LATERAL", "LIMIT 51", "LIMIT 25", "_v2_lock_room",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_endpoint_is_session_bound_read_only(self):
        tree = ast.parse((ROOT / "controllers" / "api_v2.py").read_text(encoding="utf-8"))
        routes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == "route"]
        attention = next(node for node in routes if any(
            isinstance(arg, ast.Constant) and arg.value == "/bwork/api/v2/attention"
            for arg in ast.walk(node.args[0])
        ))
        keywords = {keyword.arg: ast.literal_eval(keyword.value) for keyword in attention.keywords}
        self.assertEqual(keywords["auth"], "user")
        self.assertEqual(keywords["type"], "http")
        self.assertTrue(keywords["csrf"])

    def test_badge_refreshes_after_login_and_retries_while_v2_is_busy(self):
        activity = (ROOT.parents[1] / "android" / "bwork-legacy" / "app" / "src" / "main"
                    / "java" / "com" / "baseer" / "bwork" / "legacy"
                    / "BWorkIdentityActivity.java").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            activity.count("handler.post(this::refreshAttentionBadge);"), 3,
            "the badge must refresh after verified login, rooms, and tasks",
        )
        self.assertIn(
            "handler.postDelayed(this::refreshAttentionBadge, 350);", activity,
        )


if __name__ == "__main__":
    unittest.main()
