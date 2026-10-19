"""Regression checks for the cumulative BChat guard engine."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bchat_release_guard", ROOT / "tools" / "release_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ReleaseGuardTests(unittest.TestCase):
    def test_current_registry_is_a_valid_complete_contract_set(self):
        registry = guard.load_registry()
        self.assertTrue(guard.REQUIRED_IDS <= set(guard.entries_by_id(registry)))
        self.assertTrue(all(entry["suites"] for entry in registry["invariants"]))

    def test_unregistered_source_has_no_owner(self):
        registry = guard.load_registry()
        self.assertFalse(any(guard.matches("custom_addons/baseer_bchat/new_capability.py", entry["source_paths"])
                             for entry in registry["invariants"]))

    def test_existing_attention_source_has_its_contract(self):
        registry = guard.load_registry()
        owners = [entry["id"] for entry in registry["invariants"] if guard.matches(
            "custom_addons/baseer_bchat/models/attention_service.py", entry["source_paths"]
        )]
        self.assertEqual(owners, ["attention-center"])

    def test_login_brand_source_has_its_contract(self):
        registry = guard.load_registry()
        owners = [entry["id"] for entry in registry["invariants"] if guard.matches(
            "android/bchat/app/src/main/java/com/baseer/freshchat/LoginBrandView.java",
            entry["source_paths"],
        )]
        self.assertEqual(owners, ["login-brand-motion"])

    def test_bwork_admin_and_runtime_workflow_have_cumulative_contracts(self):
        registry = guard.load_registry()
        for path in ('custom_addons/baseer_bwork_admin/models/service.py',
                     '.github/workflows/test-bwork-admin.yml'):
            owners = [entry['id'] for entry in registry['invariants']
                      if guard.matches(path, entry['source_paths'])]
            self.assertIn('bwork-admin-metadata-and-branding', owners)

    def test_guard_integrity_covers_codeowners_and_both_ci_modes(self):
        guard.run_guard_integrity()

    def test_historical_registry_may_precede_a_new_required_invariant(self):
        registry = guard.load_registry()
        historical = dict(registry)
        historical["invariants"] = [entry for entry in registry["invariants"]
                                    if entry["id"] != "bridge-session-recovery"]
        with self.assertRaises(SystemExit):
            guard.load_registry(json.dumps(historical))
        self.assertEqual(
            guard.load_registry(json.dumps(historical), enforce_current_required=False)["schema"], 2,
        )


if __name__ == "__main__":
    unittest.main()
