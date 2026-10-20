"""Regression checks for the cumulative BWork guard engine."""
import importlib.util
import copy
import json
from pathlib import Path
import sys
import subprocess
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bwork_release_guard", ROOT / "tools" / "release_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ReleaseGuardTests(unittest.TestCase):
    def test_current_registry_is_a_valid_complete_contract_set(self):
        registry = guard.load_registry()
        self.assertTrue(guard.REQUIRED_IDS <= set(guard.entries_by_id(registry)))
        self.assertTrue(all(entry["suites"] for entry in registry["invariants"]))

    def test_unregistered_source_has_no_owner(self):
        registry = guard.load_registry()
        self.assertFalse(any(guard.matches("custom_addons/baseer_bwork/new_capability.py", entry["source_paths"])
                             for entry in registry["invariants"]))

    def test_existing_attention_source_has_its_contract(self):
        registry = guard.load_registry()
        owners = [entry["id"] for entry in registry["invariants"] if guard.matches(
            "custom_addons/baseer_bwork/models/attention_service.py", entry["source_paths"]
        )]
        self.assertEqual(owners, ["attention-center", "bwork-retention-explicit-readiness-and-content-tombstones"])

    def test_login_brand_source_has_its_contract(self):
        registry = guard.load_registry()
        owners = [entry["id"] for entry in registry["invariants"] if guard.matches(
            "android/bwork-legacy/app/src/main/java/com/baseer/bwork/legacy/LoginBrandView.java",
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

    def _baseline(self, registry, *, legacy=True):
        raw = json.dumps(registry)
        def read(command, **kwargs):
            expected = guard.LEGACY_REGISTRY_PATH if legacy else guard.REGISTRY_PATH
            if command[-1] == 'base:' + expected:
                return raw
            raise subprocess.CalledProcessError(128, command)
        return mock.patch.object(guard.subprocess, 'check_output', side_effect=read)

    def test_old_path_baseline_survives_directory_and_brand_rename(self):
        current = guard.load_registry()
        old = copy.deepcopy(current)
        for entry in old['invariants']:
            entry['scope'] = entry['scope'].replace('BWork', 'BChat').replace('baseer_bwork', 'baseer_bchat')
            entry['source_paths'] = [p.replace('custom_addons/baseer_bwork/', 'custom_addons/baseer_bchat/')
                                     .replace('android/bwork-legacy/', 'android/bchat/')
                                     .replace('/com/baseer/bwork/legacy/', '/com/baseer/freshchat/')
                                     .replace('/BWork', '/BChat') for p in entry['source_paths']]
        with self._baseline(old):
            guard.check_registry_history('base', current)

    def test_missing_or_dual_baseline_is_not_a_bootstrap_bypass(self):
        current = guard.load_registry()
        for response in (subprocess.CalledProcessError(128, ['git']), json.dumps(current)):
            with mock.patch.object(guard.subprocess, 'check_output', side_effect=response if isinstance(response, Exception) else None,
                                   return_value=response if isinstance(response, str) else None):
                with self.assertRaisesRegex(SystemExit, 'exactly one historical registry'):
                    guard.check_registry_history('base', current)

    def test_existing_contract_cannot_be_deleted_or_weakened_after_rename(self):
        original = guard.load_registry()
        variants = []
        deleted = copy.deepcopy(original)
        deleted['invariants'].pop()
        variants.append(deleted)
        for field, value in (('scope', 'Changed security meaning which is not a rename.'),
                             ('source_paths', []), ('suites', []), ('risk', 'low'),
                             ('introduced', '2026-10-21')):
            edited = copy.deepcopy(original)
            edited['invariants'][0][field] = value
            variants.append(edited)
        for edited in variants:
            with self._baseline(original, legacy=False), self.assertRaises(SystemExit):
                guard.check_registry_history('base', edited)

    def test_deleted_legacy_paths_are_owned_and_unknown_deletions_fail(self):
        current = guard.load_registry()
        with mock.patch.object(guard, 'check_registry_history'), \
                mock.patch.object(guard, 'changed_paths', return_value=['custom_addons/baseer_bchat/models/service.py']):
            self.assertIn('backend-contracts', guard.changed_guard('base', 'head', current))
        with mock.patch.object(guard, 'check_registry_history'), \
                mock.patch.object(guard, 'changed_paths', return_value=['custom_addons/baseer_bchat/new_capability.py']):
            with self.assertRaisesRegex(SystemExit, 'no cumulative contract'):
                guard.changed_guard('base', 'head', current)

    def test_legacy_required_status_adapter_cannot_turn_skipped_tests_green(self):
        original = guard.source_text
        def weakened(path):
            return original(path).replace('run: test "$CANONICAL_RESULT" = success && test "$MOBILE_RESULT" = success', 'run: true')
        with mock.patch.object(guard, 'source_text', side_effect=weakened):
            with self.assertRaisesRegex(SystemExit, 'single canonical suite actually succeeded'):
                guard.run_guard_integrity()

    def _mobile_history(self, baseline):
        def read(command, **kwargs):
            if command[-1] == 'base:mobile/chatwoot/tools/bwork-baseline.json':
                return json.dumps(baseline)
            raise subprocess.CalledProcessError(128, command)
        return mock.patch.object(guard.subprocess, 'check_output', side_effect=read)

    def test_mobile_history_allows_only_named_suite_relocation(self):
        current = json.loads(guard.source_text('mobile/bwork/tools/bwork-baseline.json'))
        old = copy.deepcopy(current)
        for item in old['invariants']:
            if item['suite'] == 'test:bwork-core':
                item['suite'] = 'test:odoo'
        with self._mobile_history(old):
            guard.check_mobile_baseline_history('base')

    def test_mobile_history_rejects_missing_behavior_or_weakened_binding(self):
        current = json.loads(guard.source_text('mobile/bwork/tools/bwork-baseline.json'))
        variants = []
        deleted = copy.deepcopy(current)
        deleted['invariants'].pop()
        variants.append(deleted)
        for field in ('test', 'description', 'suite'):
            changed = copy.deepcopy(current)
            changed['invariants'][0][field] = 'unapproved replacement'
            variants.append(changed)
        for changed in variants:
            with self._mobile_history(current), \
                    mock.patch.object(guard, 'source_text', return_value=json.dumps(changed)), \
                    self.assertRaises(SystemExit):
                guard.check_mobile_baseline_history('base')

    def test_mobile_historical_baseline_cannot_disappear_or_have_two_owners(self):
        current = guard.source_text('mobile/bwork/tools/bwork-baseline.json')
        for value in (None, current):
            with mock.patch.object(guard.subprocess, 'check_output', return_value=value,
                                   side_effect=subprocess.CalledProcessError(128, ['git']) if value is None else None), \
                    self.assertRaisesRegex(SystemExit, 'lineage missing or dual'):
                guard.check_mobile_baseline_history('base')


if __name__ == "__main__":
    unittest.main()
