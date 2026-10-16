#!/usr/bin/env python3
"""Cumulative BChat release contracts.

The registry deliberately contains names of trusted suites, not arbitrary shell
commands. A future BChat capability is accepted only when it is mapped to a
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
REGISTRY_PATH = "custom_addons/baseer_bchat/guard_registry.json"
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
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"BCHAT_GUARD=FAILED\nREASON={message}")


def source_text(relative: str) -> str:
    path = ROOT / relative
    require(path.is_file(), f"required BChat source is missing: {relative}")
    return path.read_text(encoding="utf-8")


def load_registry(raw: str | None = None, *, enforce_current_required: bool = True) -> dict:
    try:
        value = json.loads(raw if raw is not None else REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"BCHAT_GUARD=FAILED\nREASON=invalid BChat guard registry: {error}") from error
    require(isinstance(value, dict) and value.get("schema") == 2,
            "unsupported BChat guard registry schema")
    entries = value.get("invariants")
    require(isinstance(entries, list) and entries, "BChat guard registry has no invariants list")
    ids: set[str] = set()
    for entry in entries:
        require(isinstance(entry, dict), "every BChat invariant must be an object")
        invariant_id = entry.get("id")
        require(isinstance(invariant_id, str) and re.fullmatch(r"[a-z0-9-]+", invariant_id),
                "BChat invariant id is invalid")
        require(invariant_id not in ids, f"duplicate BChat invariant id: {invariant_id}")
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
        require(REQUIRED_IDS <= ids, "BChat guard registry does not cover all protected invariants")
    return value


def entries_by_id(registry: dict) -> dict[str, dict]:
    return {entry["id"]: entry for entry in registry["invariants"]}


def check_registry_history(base: str, current: dict) -> None:
    """Make the registry append-only; protected fields may only be extended."""
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{base}:{REGISTRY_PATH}"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        # This is the one bootstrap PR which introduces the guard.
        return
    # A historical registry legitimately predates a newly introduced required
    # invariant. It must still be structurally valid so that its entries cannot
    # be deleted or weakened by the current candidate.
    previous = load_registry(raw, enforce_current_required=False)
    old_entries = entries_by_id(previous)
    new_entries = entries_by_id(current)
    for invariant_id, old in old_entries.items():
        new = new_entries.get(invariant_id)
        require(new is not None, f"protected invariant was deleted: {invariant_id}")
        require(new["scope"] == old["scope"],
                f"scope changed for {invariant_id}; register a new invariant instead")
        require(RISK_ORDER[new["risk"]] >= RISK_ORDER[old["risk"]],
                f"risk was weakened for {invariant_id}")
        require(set(new["source_paths"]) >= set(old["source_paths"]),
                f"source coverage was removed from {invariant_id}")
        require(set(new["suites"]) >= set(old["suites"]),
                f"test coverage was removed from {invariant_id}")


def check_backend() -> None:
    manifest = source_text("custom_addons/baseer_bchat/__manifest__.py")
    service = source_text("custom_addons/baseer_bchat/models/service.py")
    v2 = source_text("custom_addons/baseer_bchat/models/v2_service.py")
    attention = source_text("custom_addons/baseer_bchat/models/attention_service.py")
    controller = source_text("custom_addons/baseer_bchat/controllers/api_v2.py")
    task = source_text("custom_addons/baseer_bchat/models/task.py")
    receipt = source_text("custom_addons/baseer_bchat/models/message_receipt.py")
    require("'version'" in manifest, "BChat module version is absent")
    require("_require_any_bchat_permission" in service, "permission boundary is absent")
    require("joined_after_message_id" in v2 and "_v2_current_member" in v2,
            "membership epoch gate is absent")
    require("baseer_bchat_receipt_unread_member_idx" in receipt,
            "unread receipt index is absent")
    require("def _v2_attention" in attention and "badge_count" in attention,
            "attention-center contract is absent")
    require("assignee_id" in attention and "joined_after_message_id" in attention
            and "JOIN LATERAL" in attention and "LIMIT 51" in attention,
            "attention-center scope is not assignee and membership epoch based")
    require("/bchat/api/v2/attention" in controller,
            "attention-center HTTP route is absent")
    require("baseer_bchat_task_assignee_state_id_idx" in task,
            "attention task index is absent")


def check_android_source() -> None:
    gradle = source_text("android/bchat/app/build.gradle")
    push_manifest = source_text("android/bchat/app/src/gradle/AndroidManifestPush.xml")
    builder = source_text("android/bchat/tools/build-unified-preview.ps1")
    package_check = source_text("android/bchat/tools/check-package.py")
    require("bchatEnablePush" in gradle and "AndroidManifestPush.xml" in gradle,
            "Gradle no longer selects the Push manifest explicitly")
    require("BChatFirebaseMessagingService" in push_manifest and "com.google.firebase.MESSAGING_EVENT" in push_manifest,
            "Push manifest is missing the Firebase service contract")
    require("BCHAT_PUSH_ENABLED" in gradle, "Push build config flag is absent")
    require("BChatFirebaseMessagingService" in builder and "com.google.firebase.MESSAGING_EVENT" in builder,
            "APK builder no longer validates the signed artifact Push contract")
    require("BChatFirebaseMessagingService" in package_check and "AndroidManifestPush.xml" in package_check,
            "Android source contract no longer validates the Push manifest")
    activity = source_text("android/bchat/app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java")
    require(activity.count("handler.post(this::refreshAttentionBadge);") >= 3
            and "handler.postDelayed(this::refreshAttentionBadge, 350);" in activity,
            "attention badge no longer refreshes after login or retries the busy v2 channel")


def check_release_wrappers() -> None:
    qa = source_text("ops/qa/baseer-qa-deploy")
    live = source_text("ops/production/baseer-production-deploy")
    workflow = source_text(".github/workflows/validate-pull-request.yml")
    command = "custom_addons/baseer_bchat/tools/release_guard.py"
    require(command in qa and command in live,
            "QA or Live deployment no longer invokes the BChat guard")
    require(command in workflow and "--changed" in workflow,
            "pull-request workflow no longer runs cumulative BChat contracts")


def run_backend_contracts() -> None:
    subprocess.run([
        sys.executable, "-m", "unittest", "discover", "-s",
        "custom_addons/baseer_bchat/tests_contract", "-p", "test_*.py", "-v",
    ], cwd=ROOT, check=True)


def run_android_source_contract() -> None:
    for source_test in (
        "android/bchat/tools/check-package.py",
        "android/bchat/tools/test-entry-layout-contracts.py",
        "android/bchat/tools/test-localization.py",
        "android/bchat/tools/test-bchat-user-permissions.py",
        "android/bchat/tools/test-verified-read-fallback.py",
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
    source = source_text("custom_addons/baseer_bchat/tools/release_guard.py")
    require("check_registry_history" in source,
            "registry monotonicity check is absent")
    owners = source_text(".github/CODEOWNERS")
    for protected in (
        "/custom_addons/baseer_bchat/guard_registry.json",
        "/custom_addons/baseer_bchat/tools/release_guard.py",
        "/.github/workflows/validate-pull-request.yml",
        "/.github/workflows/bchat-cumulative-contracts.yml",
        "/ops/qa/baseer-qa-deploy",
        "/ops/production/baseer-production-deploy",
    ):
        matching = [line.split() for line in owners.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                    and line.split()[0] == protected]
        require(bool(matching) and any(owner.startswith("@") for owner in matching[0][1:]),
                f"CODEOWNERS does not assign an explicit owner to {protected}")
    workflow = source_text(".github/workflows/bchat-cumulative-contracts.yml")
    require("release_guard.py --changed" in workflow and "release_guard.py --all" in workflow,
            "BChat workflow no longer runs both PR and manual guard modes")
    requirements = source_text("custom_addons/baseer_bchat/tests_contract/requirements-ci.txt")
    require("Pillow==12.3.0" in requirements and "--hash=sha256:" in requirements,
            "BChat media-test dependency is not version and hash pinned")
    source_workflow = source_text(".github/workflows/validate-pull-request.yml")
    require("requirements-ci.txt" in workflow and "--require-hashes" in workflow
            and "requirements-ci.txt" in source_workflow and "--require-hashes" in source_workflow,
            "BChat media-test dependency is not installed by every guard workflow")


def run_bridge_entry_contract() -> None:
    subprocess.run([
        sys.executable, "-m", "unittest", "discover", "-s",
        "custom_addons/baseer_bchat/tests_contract", "-p",
        "test_bridge_entry_contract.py", "-v",
    ], cwd=ROOT, check=True)


RUNNERS: dict[str, Callable[[], None]] = {
    "backend-contracts": run_backend_contracts,
    "android-source-contract": run_android_source_contract,
    "apk-artifact": run_apk_artifact,
    "release-wrapper": check_release_wrappers,
    "source-structure": run_source_structure,
    "guard-integrity": run_guard_integrity,
    "bridge-entry-contract": run_bridge_entry_contract,
}


def changed_paths(base: str, head: str) -> list[str]:
    return subprocess.check_output(
        ["git", "diff", "--name-only", base, head], cwd=ROOT, text=True
    ).splitlines()


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def changed_guard(base: str, head: str, registry: dict) -> set[str]:
    paths = changed_paths(base, head)
    relevant = [path for path in paths if path.startswith((
        "custom_addons/baseer_bchat/", "android/bchat/", "ops/qa/baseer-qa-deploy",
        "ops/production/baseer-production-deploy", ".github/workflows/validate-pull-request.yml",
        ".github/workflows/bchat-cumulative-contracts.yml", ".github/CODEOWNERS",
    ))]
    if not relevant:
        return set()
    check_registry_history(base, registry)
    coverage: set[str] = set()
    unowned: list[str] = []
    for path in relevant:
        owners = [entry for entry in registry["invariants"] if matches(path, entry["source_paths"])]
        if not owners:
            unowned.append(path)
            continue
        coverage.update(suite for entry in owners for suite in entry["suites"])
    require(not unowned,
            "BChat change has no cumulative contract; register source path and named suite: " + ", ".join(unowned))
    return coverage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed", nargs=2, metavar=("BASE", "HEAD"))
    parser.add_argument("--suite", action="append", choices=sorted(SUITES), default=[])
    parser.add_argument("--all", action="store_true", help="run every trusted suite")
    args = parser.parse_args()
    registry = load_registry()
    selected = set(args.suite)
    if args.changed:
        selected.update(changed_guard(*args.changed, registry))
    if args.all:
        selected.update(SUITES)
    if not selected:
        selected = {"source-structure", "guard-integrity"}
    for suite in sorted(selected):
        RUNNERS[suite]()
        print(f"BCHAT_GUARD_SUITE=PASS:{suite}")
    print("BCHAT_GUARD=PASS")


if __name__ == "__main__":
    main()
