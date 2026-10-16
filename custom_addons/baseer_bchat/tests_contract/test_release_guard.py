"""Regression checks for the cumulative BChat guard engine."""
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
