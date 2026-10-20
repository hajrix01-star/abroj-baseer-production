"""Regression checks for the cumulative BChat guard engine."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


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
        self.assertEqual(owners, ["attention-center", "bwork-retention-explicit-readiness-and-content-tombstones"])

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

    def _prior_ci_wiring(self, path):
        value = self._original_source_text(path)
        if path == '.github/workflows/validate-pull-request.yml':
            # Module-scoped QA overlays deliberately retain the prior workflow.
            # Preserve every older assertion's input; remove only new CI names.
            value = value.replace('baseer_bwork_admin', 'baseer_prior_admin')
            value = value.replace('test-bwork-admin', 'test-prior-admin')
        return value

    def test_default_module_overlay_preserves_prior_runtime_guards(self):
        self._original_source_text = guard.source_text
        with mock.patch.object(guard, 'source_text', side_effect=self._prior_ci_wiring), \
                mock.patch.object(sys, 'argv', ['release_guard.py']):
            guard.main()

    def test_changed_repository_mode_rejects_missing_new_ci_wiring(self):
        self._original_source_text = guard.source_text
        with mock.patch.object(guard, 'source_text', side_effect=self._prior_ci_wiring), \
                mock.patch.object(sys, 'argv', ['release_guard.py', '--changed', 'base', 'head']), \
                mock.patch.object(guard, 'changed_guard', return_value=set()), \
                mock.patch.object(guard, 'RUNNERS', {key: lambda: None for key in guard.SUITES}):
            with self.assertRaisesRegex(SystemExit, 'administrative changes no longer activate'):
                guard.main()

    def test_all_repository_mode_rejects_missing_new_ci_wiring(self):
        self._original_source_text = guard.source_text
        with mock.patch.object(guard, 'source_text', side_effect=self._prior_ci_wiring), \
                mock.patch.object(sys, 'argv', ['release_guard.py', '--all']), \
                mock.patch.object(guard, 'RUNNERS', {key: lambda: None for key in guard.SUITES}):
            with self.assertRaisesRegex(SystemExit, 'administrative changes no longer activate'):
                guard.main()

    def test_repository_modes_keep_new_ci_wiring_mandatory(self):
        for arguments in (['--all'], ['--changed', 'base', 'head']):
            with mock.patch.object(sys, 'argv', ['release_guard.py', *arguments]), \
                    mock.patch.object(guard, 'changed_guard', return_value=set()), \
                    mock.patch.object(guard, 'RUNNERS', {key: lambda: None for key in guard.SUITES}):
                guard.main()

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
