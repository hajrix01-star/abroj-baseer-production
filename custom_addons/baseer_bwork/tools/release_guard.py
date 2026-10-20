#!/usr/bin/env python3
"""Cumulative BWork release contracts.

The registry deliberately contains names of trusted suites, not arbitrary shell
commands. A future BWork capability is accepted only when it is mapped to a
named suite and source area here; all prior contracts stay active on every PR
and in the QA/Live release wrappers.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = "custom_addons/baseer_bwork/guard_registry.json"
LEGACY_REGISTRY_PATH = "custom_addons/baseer_bchat/guard_registry.json"
REGISTRY = ROOT / REGISTRY_PATH
RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
SUITES = {
    "backend-contracts",
    "android-source-contract",
    "apk-artifact",
    "release-wrapper",
    "source-structure",
    "guard-integrity",
    "bridge-entry-contract",
    "canonical-ops-contract",
}
REQUIRED_IDS = {
    "private-api-permissions",
    "membership-epochs",
    "task-transitions",
    "push-enabled-apk",
    "attention-center",
    "bridge-session-recovery",
    "verified-webview-read-fallback",
    "qa-live-release-gate",
    "guard-engine-integrity",
    "task-push-fastlane-and-private-avatars",
    "media-send-ack-reconciliation",
    "native-capability-media-upload",
    "modern-work-task-scope-replay-reminders",
    "bwork-admin-metadata-and-branding",
    "bwork-retention-explicit-readiness-and-content-tombstones",
    "canonical-identity-migration-and-wire-compatibility",
    "canonical-client-identity-and-protected-behavior-lineage",
    "canonical-backend-source-lineage",
    "canonical-legacy-preview-source-lineage",
}


def canonical_path(path: str) -> str:
    """Fixed source lineage only, not a replacement rule for stored data."""
    replacements = (
        ("custom_addons/baseer_bchat_document_permission_guards/", "custom_addons/baseer_bwork_document_permission_guards/"),
        ("custom_addons/baseer_bchat_permission_guards/", "custom_addons/baseer_bwork_permission_guards/"),
        ("custom_addons/baseer_bchat_procurement/", "custom_addons/baseer_bwork_procurement/"),
        ("custom_addons/baseer_bchat/", "custom_addons/baseer_bwork/"),
        ("android/bchat/", "android/bwork-legacy/"),
        ("mobile/chatwoot/", "mobile/bwork/"),
        (".github/workflows/bchat-cumulative-contracts.yml", ".github/workflows/bwork-cumulative-contracts.yml"),
    )
    for old, new in replacements:
        if path.startswith(old):
            path = new + path[len(old):]
            break
    if path.startswith("android/bwork-legacy/"):
        path = path.replace("/com/baseer/freshchat/", "/com/baseer/bwork/legacy/")
        path = path.replace("/OdooIdentityActivity.java", "/BWorkIdentityActivity.java")
        path = path.replace('/bchat_local_ca.crt', '/bwork_local_ca.crt')
        path = path.replace('/bchat_network_security.xml', '/bwork_network_security.xml')
        path = path.replace("/BChat", "/BWork").replace("test-bchat-user-permissions", "test-bwork-user-permissions")
    return path


def historical_scope(scope: str) -> str:
    # Exact branding substitutions in historical invariant prose only.
    return scope.replace("BChat", "BWork").replace("baseer_bchat", "baseer_bwork")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"BWORK_GUARD=FAILED\nREASON={message}")


def source_text(relative: str) -> str:
    path = ROOT / relative
    require(path.is_file(), f"required BWork source is missing: {relative}")
    return path.read_text(encoding="utf-8")


def load_registry(raw: str | None = None, *, enforce_current_required: bool = True) -> dict:
    try:
        value = json.loads(raw if raw is not None else REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"BWORK_GUARD=FAILED\nREASON=invalid BWork guard registry: {error}") from error
    require(isinstance(value, dict) and value.get("schema") == 2,
            "unsupported BWork guard registry schema")
    entries = value.get("invariants")
    require(isinstance(entries, list) and entries, "BWork guard registry has no invariants list")
    ids: set[str] = set()
    for entry in entries:
        require(isinstance(entry, dict), "every BWork invariant must be an object")
        invariant_id = entry.get("id")
        require(isinstance(invariant_id, str) and re.fullmatch(r"[a-z0-9-]+", invariant_id),
                "BWork invariant id is invalid")
        require(invariant_id not in ids, f"duplicate BWork invariant id: {invariant_id}")
        ids.add(invariant_id)
        require(isinstance(entry.get("introduced"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["introduced"]),
                f"{invariant_id} needs an introduced date")
        require(entry.get("risk") in RISK_ORDER, f"{invariant_id} has an invalid risk")
        require(isinstance(entry.get("scope"), str) and len(entry["scope"].strip()) >= 24,
                f"{invariant_id} needs a precise scope")
        paths = entry.get("source_paths")
        require(isinstance(paths, list) and all(isinstance(path, str) and path for path in paths),
                f"{invariant_id} needs source paths")
        suites = entry.get("suites")
        require(isinstance(suites, list) and suites and set(suites) <= SUITES,
                f"{invariant_id} references an unknown or empty suite")
    if enforce_current_required:
        require(REQUIRED_IDS <= ids, "BWork guard registry does not cover all protected invariants")
    return value


def entries_by_id(registry: dict) -> dict[str, dict]:
    return {entry["id"]: entry for entry in registry["invariants"]}


def check_registry_history(base: str, current: dict) -> None:
    """Make the registry append-only; protected fields may only be extended."""
    baselines = []
    for path in (REGISTRY_PATH, LEGACY_REGISTRY_PATH):
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{base}:{path}"], cwd=ROOT, text=True,
                stderr=subprocess.DEVNULL,
            )
            baselines.append((path, raw))
        except subprocess.CalledProcessError:
            pass
    require(len(baselines) == 1,
            "expected exactly one historical registry; missing or dual lineage cannot bootstrap silently")
    historical_path, raw = baselines[0]
    # A historical registry legitimately predates a newly introduced required
    # invariant. It must still be structurally valid so that its entries cannot
    # be deleted or weakened by the current candidate.
    previous = load_registry(raw, enforce_current_required=False)
    old_entries = entries_by_id(previous)
    new_entries = entries_by_id(current)
    for invariant_id, old in old_entries.items():
        new = new_entries.get(invariant_id)
        require(new is not None, f"protected invariant was deleted: {invariant_id}")
        expected_scope = historical_scope(old["scope"]) if historical_path == LEGACY_REGISTRY_PATH else old["scope"]
        require(new["scope"] == expected_scope,
                f"scope changed for {invariant_id}; register a new invariant instead")
        require(new["introduced"] == old["introduced"], f"introduction date changed for {invariant_id}")
        require(RISK_ORDER[new["risk"]] >= RISK_ORDER[old["risk"]],
                f"risk was weakened for {invariant_id}")
        require(set(new["source_paths"]) >= {canonical_path(path) for path in old["source_paths"]},
                f"source coverage was removed from {invariant_id}")
        require(set(new["suites"]) >= set(old["suites"]),
                f"test coverage was removed from {invariant_id}")


def check_mobile_baseline_history(base: str) -> None:
    """Keep all prior protected tests; script-suite rename is not test deletion."""
    previous = []
    for path in ('mobile/bwork/tools/bwork-baseline.json', 'mobile/chatwoot/tools/bwork-baseline.json'):
        try:
            previous.append(json.loads(subprocess.check_output(
                ['git', 'show', f'{base}:{path}'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)))
        except subprocess.CalledProcessError:
            pass
    require(len(previous) == 1, 'mobile baseline historical lineage missing or dual')
    current = json.loads(source_text('mobile/bwork/tools/bwork-baseline.json'))
    new = {row['id']: row for row in current['invariants']}
    require(len(new) == len(current['invariants']), 'duplicate mobile invariant')
    for old in previous[0]['invariants']:
        row = new.get(old['id'])
        require(row is not None, 'protected mobile behavior deleted: ' + old['id'])
        require(row['test'] == old['test'] and row['description'] == old['description'],
                'protected mobile behavior changed without separate approval: ' + old['id'])
        expected_suite = {'test:odoo': 'test:bwork-core'}.get(old['suite'], old['suite'])
        require(row['suite'] == expected_suite, 'protected mobile suite changed: ' + old['id'])


def check_backend() -> None:
    manifest = source_text("custom_addons/baseer_bwork/__manifest__.py")
    service = source_text("custom_addons/baseer_bwork/models/service.py")
    v2 = source_text("custom_addons/baseer_bwork/models/v2_service.py")
    attention = source_text("custom_addons/baseer_bwork/models/attention_service.py")
    controller = source_text("custom_addons/baseer_bwork/controllers/api_v2.py")
    task = source_text("custom_addons/baseer_bwork/models/task.py")
    receipt = source_text("custom_addons/baseer_bwork/models/message_receipt.py")
    push = source_text("custom_addons/baseer_bwork/models/push.py")
    avatars = source_text("custom_addons/baseer_bwork/models/avatar_service.py")
    require("'version'" in manifest, "BWork module version is absent")
    require("_require_any_bwork_permission" in service, "permission boundary is absent")
    require("joined_after_message_id" in v2 and "_v2_current_member" in v2,
            "membership epoch gate is absent")
    require("baseer_bwork_receipt_unread_member_idx" in receipt,
            "unread receipt index is absent")
    require("def _v2_attention" in attention and "badge_count" in attention,
            "attention-center contract is absent")
    require("assignee_id" in attention and "joined_after_message_id" in attention
            and "JOIN LATERAL" in attention and "LIMIT 51" in attention,
            "attention-center scope is not assignee and membership epoch based")
    require("/bwork/api/v2/attention" in controller,
            "attention-center HTTP route is absent")
    require("baseer_bwork_task_assignee_state_id_idx" in task,
            "attention task index is absent")
    require("self.env.cr.postcommit.add(submit)" in push
            and "def _dispatch_event_ids" in push
            and "ThreadPoolExecutor" in push,
            "durable post-commit BWork push fast lane is absent")
    require("def _v2_member_avatar" in avatars and "_v2_current_member" in avatars
            and "image_128" in avatars
            and "/bwork/api/v2/rooms/<int:room_id>/members/<int:user_id>/avatar" in controller,
            "private BWork employee avatar contract is absent")


def check_android_source() -> None:
    gradle = source_text("android/bwork-legacy/app/build.gradle")
    push_manifest = source_text("android/bwork-legacy/app/src/gradle/AndroidManifestPush.xml")
    builder = source_text("android/bwork-legacy/tools/build-unified-preview.ps1")
    package_check = source_text("android/bwork-legacy/tools/check-package.py")
    require("bworkEnablePush" in gradle and "AndroidManifestPush.xml" in gradle,
            "Gradle no longer selects the Push manifest explicitly")
    require("BWorkFirebaseMessagingService" in push_manifest and "com.google.firebase.MESSAGING_EVENT" in push_manifest,
            "Push manifest is missing the Firebase service contract")
    require("BWORK_PUSH_ENABLED" in gradle, "Push build config flag is absent")
    require("BWorkFirebaseMessagingService" in builder and "com.google.firebase.MESSAGING_EVENT" in builder,
            "APK builder no longer validates the signed artifact Push contract")
    require("BWorkFirebaseMessagingService" in package_check and "AndroidManifestPush.xml" in package_check,
            "Android source contract no longer validates the Push manifest")
    activity = source_text("android/bwork-legacy/app/src/main/java/com/baseer/bwork/legacy/BWorkIdentityActivity.java")
    require(activity.count("handler.post(this::refreshAttentionBadge);") >= 3
            and "handler.postDelayed(this::refreshAttentionBadge, 350);" in activity,
            "attention badge no longer refreshes after login or retries the busy v2 channel")
    require("privateAvatarView" in activity and "V2_PROFILE_AVATAR" in activity
            and "members/\" + authorId + \"/avatar" in activity,
            "private employee-avatar presentation is absent")
    require("reconcilePendingMediaFromVerifiedHistory" in activity
            and "mediaStore.pendingForRoom(scopedAccount" in activity
            and "confirmedMediaIds.contains(entry.mediaId)" in activity
            and "mediaStore.acknowledge(scopedAccount, entry);" in activity,
            "media send acknowledgement recovery is absent")


def check_release_wrappers() -> None:
    qa = source_text("ops/qa/baseer-qa-deploy")
    live = source_text("ops/production/baseer-production-deploy")
    workflow = source_text(".github/workflows/validate-pull-request.yml")
    command = "custom_addons/baseer_bwork/tools/release_guard.py"
    require(command in qa and command in live,
            "QA or Live deployment no longer invokes the BWork guard")
    require(command in workflow and "--changed" in workflow,
            "pull-request workflow no longer runs cumulative BWork contracts")


def run_backend_contracts() -> None:
    subprocess.run([
        sys.executable, "-m", "unittest", "discover", "-s",
        "custom_addons/baseer_bwork/tests_contract", "-p", "test_*.py", "-v",
    ], cwd=ROOT, check=True)


def run_android_source_contract() -> None:
    for source_test in (
        "android/bwork-legacy/tools/check-package.py",
        "android/bwork-legacy/tools/test-entry-layout-contracts.py",
        "android/bwork-legacy/tools/test-localization.py",
        "android/bwork-legacy/tools/test-orders-ui-contracts.py",
        "android/bwork-legacy/tools/test-bwork-user-permissions.py",
        "android/bwork-legacy/tools/test-connected-media-ui-contracts.py",
        "android/bwork-legacy/tools/test-connected-media-journey.py",
        "android/bwork-legacy/tools/test-verified-read-fallback.py",
        "android/bwork-legacy/tools/test-login-brand-contracts.py",
    ):
        subprocess.run([sys.executable, source_test], cwd=ROOT, check=True)


def run_apk_artifact() -> None:
    # The signed-artifact check runs in build-unified-preview.ps1 only after
    # the APK exists. This source suite proves that hook remains mandatory.
    check_android_source()


def run_source_structure() -> None:
    check_backend()
    check_android_source()
    check_release_wrappers()


def run_guard_integrity() -> None:
    load_registry()
    source = source_text("custom_addons/baseer_bwork/tools/release_guard.py")
    require("check_registry_history" in source,
            "registry monotonicity check is absent")
    owners = source_text(".github/CODEOWNERS")
    for protected in (
        "/custom_addons/baseer_bwork/guard_registry.json",
        "/custom_addons/baseer_bwork/tools/release_guard.py",
        "/custom_addons/baseer_bwork/tools/canonical_pre_upgrade.py",
        "/custom_addons/baseer_bwork/canonical_name_map.json",
        "/custom_addons/baseer_bwork/compatibility.py",
        "/.github/workflows/validate-pull-request.yml",
        "/.github/workflows/bwork-cumulative-contracts.yml",
        "/.github/workflows/test-bwork-canonical-migration.yml",
        "/ops/qa/baseer-qa-deploy",
        "/ops/production/baseer-production-deploy",
        "/ops/lib/bwork_release_source.py",
        "/mobile/bwork/tools/bwork-baseline.json",
        "/mobile/bwork/tools/check-bwork.cjs",
        "/mobile/bwork/native/sdk-contract.json",
        "/mobile/bwork/native/sdk-resolver/**",
    ):
        matching = [line.split() for line in owners.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                    and line.split()[0] == protected]
        require(bool(matching) and any(owner.startswith("@") for owner in matching[0][1:]),
                f"CODEOWNERS does not assign an explicit owner to {protected}")
    workflow = source_text(".github/workflows/bwork-cumulative-contracts.yml")
    require("release_guard.py --changed" in workflow and "release_guard.py --all" in workflow,
            "BWork workflow no longer runs both PR and manual guard modes")
    require("name: BChat cumulative contracts" in workflow
            and "needs: [contracts, mobile-contracts]" in workflow and "if: ${{ always() }}" in workflow
            and 'CANONICAL_RESULT: ${{ needs.contracts.result }}' in workflow
            and 'MOBILE_RESULT: ${{ needs.mobile-contracts.result }}' in workflow
            and 'run: test "$CANONICAL_RESULT" = success && test "$MOBILE_RESULT" = success' in workflow,
            "legacy required status must fail unless the single canonical suite actually succeeded")
    requirements = source_text("custom_addons/baseer_bwork/tests_contract/requirements-ci.txt")
    require("Pillow==12.3.0" in requirements and "--hash=sha256:" in requirements,
            "BWork media-test dependency is not version and hash pinned")
    source_workflow = source_text(".github/workflows/validate-pull-request.yml")
    require("requirements-ci.txt" in workflow and "--require-hashes" in workflow
            and "requirements-ci.txt" in source_workflow and "--require-hashes" in source_workflow,
            "BWork media-test dependency is not installed by every guard workflow")


def check_repository_ci_wiring() -> None:
    # Canonical repository checks must inspect current CI activation. A bounded
    # module deployment intentionally retains the host's unrelated workflow
    # files, so that assertion belongs to both repository modes, not the
    # default runtime guard. All pre-existing runtime guard checks remain.
    source_workflow = source_text(".github/workflows/validate-pull-request.yml")
    for old_source in (
        'custom_addons/baseer_bchat/__manifest__.py',
        'custom_addons/baseer_bchat_procurement/__manifest__.py',
        'custom_addons/baseer_bchat_permission_guards/__manifest__.py',
        'custom_addons/baseer_bchat_document_permission_guards/__manifest__.py',
        'mobile/chatwoot/package.json', 'android/bchat/app/build.gradle',
        '.github/workflows/bchat-cumulative-contracts.yml',
    ):
        require(not (ROOT / old_source).exists(), 'legacy active source reintroduced: ' + old_source)
    cumulative = source_text('.github/workflows/bwork-cumulative-contracts.yml')
    migration = source_text('.github/workflows/test-bwork-canonical-migration.yml')
    require('\n  workflow_dispatch:' in migration and '\n  pull_request:' not in migration
            and 'BWORK_CANONICAL_SYNTHETIC:' in migration
            and 'bash ops/tests/run-bwork-canonical-ci.sh' in migration
            and all(marker in migration for marker in ('BCR_NATIVE_UPGRADE_GO',
                    'BCR_FRESH_NEXT_UPGRADE_GO', 'BCR_PAIRED_BACKUP_RECOVERY_GO')),
            'deferred native migration rehearsal lost its explicit authorization boundary or required proof')
    require('pnpm --dir mobile/bwork check:bwork' in cumulative
            and 'pnpm --dir mobile/bwork test:native-session' in cumulative
            and 'install --frozen-lockfile' in cumulative
            and 'native/sdk-resolver prepareNativeProof --no-daemon' in cumulative,
            'canonical mobile protected gate is not wired to real native and locked dependency checks')
    source = source_text("custom_addons/baseer_bwork/tools/release_guard.py")
    activation = re.search(r"grep -Eq '([^']+)'", source_workflow)
    require(activation is not None and re.search(activation[1], 'custom_addons/baseer_bwork_admin/models/service.py')
            and "test-bwork-admin" in source_workflow
            and '"custom_addons/baseer_bwork_admin/"' in source,
            "BWork administrative changes no longer activate cumulative contracts")
    gallery_workflow = source_text(".github/workflows/test-bwork-gallery.yml")
    require("test-bwork-gallery" in source_workflow
            and "BWorkGalleryCase" in gallery_workflow and "BWorkGalleryHttpCase" in gallery_workflow
            and '" -eq 9' in gallery_workflow and "contents: read" in gallery_workflow,
            "BWork gallery no longer activates its isolated ORM and HTTP contract tests")
    retention_workflow = source_text(".github/workflows/test-bwork-retention.yml")
    require("test-bwork-retention" in source_workflow
            and "BWorkRetentionCase" in retention_workflow and "BWorkRetentionHttpCase" in retention_workflow
            and '" -eq 12' in retention_workflow and "contents: read" in retention_workflow,
            "BWork retention no longer activates its isolated ORM and HTTP contract tests")


def run_bridge_entry_contract() -> None:
    subprocess.run([
        sys.executable, "-m", "unittest", "discover", "-s",
        "custom_addons/baseer_bwork/tests_contract", "-p",
        "test_bridge_entry_contract.py", "-v",
    ], cwd=ROOT, check=True)


def run_canonical_ops_contract() -> None:
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s',
                    'ops/tests', '-p', 'test_bwork_release_source.py', '-v'], cwd=ROOT, check=True)


RUNNERS: dict[str, Callable[[], None]] = {
    "backend-contracts": run_backend_contracts,
    "android-source-contract": run_android_source_contract,
    "apk-artifact": run_apk_artifact,
    "release-wrapper": check_release_wrappers,
    "source-structure": run_source_structure,
    "guard-integrity": run_guard_integrity,
    "bridge-entry-contract": run_bridge_entry_contract,
    "canonical-ops-contract": run_canonical_ops_contract,
}


def changed_paths(base: str, head: str) -> list[str]:
    return subprocess.check_output(
        ["git", "diff", "--name-only", base, head], cwd=ROOT, text=True
    ).splitlines()


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def changed_guard(base: str, head: str, registry: dict) -> set[str]:
    # Git can report deletions and additions rather than renames. Both sides
    # belong to the same canonical ownership; never drop the deleted side.
    paths = sorted({canonical_path(path) for path in changed_paths(base, head)})
    relevant = [path for path in paths if path.startswith((
        "mobile/bwork/",
        "custom_addons/baseer_bwork/", "custom_addons/baseer_bwork_admin/",
        "custom_addons/baseer_bwork_procurement/", "custom_addons/baseer_bwork_permission_guards/",
        "custom_addons/baseer_bwork_document_permission_guards/", "custom_addons/baseer_bwork_dashboard/",
        "ops/lib/bwork_release_source.py", "ops/tests/test_bwork_release_source.py",
        "ops/tests/run-bwork-canonical-ci.sh", "ops/tests/fixtures/",
        ".github/workflows/test-bwork-canonical-migration.yml",
        "custom_addons/baseer_access_roles/models/res_users.py",
        "custom_addons/baseer_access_roles/tests/test_cashier_procurement_role.py",
        "custom_addons/baseer_procurement_requests/models/procurement.py",
        "custom_addons/baseer_procurement_requests/tests/test_procurement_flow.py",
        ".github/workflows/test-bwork-admin.yml", ".github/workflows/test-bwork-gallery.yml", ".github/workflows/test-bwork-retention.yml", "android/bwork-legacy/", "ops/qa/baseer-qa-deploy",
        "ops/production/baseer-production-deploy", ".github/workflows/validate-pull-request.yml",
        ".github/workflows/bwork-cumulative-contracts.yml", ".github/CODEOWNERS",
    ))]
    if not relevant:
        return set()
    check_registry_history(base, registry)
    if any(path.startswith('mobile/bwork/') for path in relevant):
        check_mobile_baseline_history(base)
    coverage: set[str] = set()
    unowned: list[str] = []
    for path in relevant:
        owners = [entry for entry in registry["invariants"] if matches(path, entry["source_paths"])]
        if not owners:
            unowned.append(path)
            continue
        coverage.update(suite for entry in owners for suite in entry["suites"])
    require(not unowned,
            "BWork change has no cumulative contract; register source path and named suite: " + ", ".join(unowned))
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed", nargs=2, metavar=("BASE", "HEAD"))
    parser.add_argument("--suite", action="append", choices=sorted(SUITES), default=[])
    parser.add_argument("--all", action="store_true", help="run every trusted suite")
    args = parser.parse_args()
    registry = load_registry()
    if args.changed or args.all:
        check_repository_ci_wiring()
    selected = set(args.suite)
    if args.changed:
        selected.update(changed_guard(*args.changed, registry))
    if args.all:
        selected.update(SUITES)
    if not selected:
        selected = {"source-structure", "guard-integrity"}
    for suite in sorted(selected):
        RUNNERS[suite]()
        print(f"BWORK_GUARD_SUITE=PASS:{suite}")
    print("BWORK_GUARD=PASS")


if __name__ == "__main__":
    main()
