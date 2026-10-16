"""Offline contract checks for the per-user BChat attention center.

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
            "def _v2_attention", "_require_any_bchat_permission", "user.company_ids.ids",
            "joined_after_message_id", "assignee_id", "badge_count", "min(50",
            "limit=25", "_v2_current_member",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_endpoint_is_session_bound_read_only(self):
        tree = ast.parse((ROOT / "controllers" / "api_v2.py").read_text(encoding="utf-8"))
        routes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == "route"]
        attention = next(node for node in routes if any(
            isinstance(arg, ast.Constant) and arg.value == "/bchat/api/v2/attention"
            for arg in node.args
        ))
        keywords = {keyword.arg: ast.literal_eval(keyword.value) for keyword in attention.keywords}
        self.assertEqual(keywords["auth"], "user")
        self.assertEqual(keywords["type"], "http")
        self.assertTrue(keywords["csrf"])


if __name__ == "__main__":
    unittest.main()
