#!/usr/bin/env python3
"""Build a QA-ID-free Noorix source manifest for the MAIN rehearsal writer.

The legacy frozen payloads are *evidence* from QA.  This tool intentionally
does not make them a runtime input: it emits a new source-only contract with
target IDs, QA database identity and old move IDs removed.  A later Odoo-side
rebind step must resolve every target reference afresh in the named rehearsal
database before it can write anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "baseer-noorix-main-source-manifest/v1"
QA_DATABASE = "baseer_noorix_data_migration_qa_20260912"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FORBIDDEN_EXACT = {
    "target_database", "original_move_id", "run_prefix", "run", "run_name",
    "required_runtime_contract",
}
RENAME = {
    "target_product_code": "decision_product_code",
    "target_product_name": "decision_product_name",
    "target_account_code": "decision_account_code",
    "target_account_type": "decision_account_type",
    "target_payment_journal_code": "decision_payment_journal_code",
    "target_purchase_journal_code": "decision_purchase_journal_code",
}


class ManifestError(ValueError):
    """Input is not safe to turn into a source-only manifest."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_forbidden_key(key: str) -> bool:
    return (
        key in FORBIDDEN_EXACT
        or key.startswith("target_")
        or key.startswith("original_")
        or key.startswith("run_")
        or key.endswith("_run_name")
        or ((key == "id" or key.endswith("_id") or key.endswith("_ids")) and not key.startswith("source_"))
    )


def removed_category(key: str) -> str:
    if key.startswith("target_"):
        return "resolved_target_reference"
    if key == "target_database":
        return "qa_database_identity"
    if key in {"run_prefix", "run"}:
        return "legacy_execution_identity"
    if key.startswith("original_"):
        return "legacy_original_reference"
    if key.startswith("run_"):
        return "legacy_execution_identity"
    if key.endswith("_run_name"):
        return "legacy_execution_identity"
    if key == "id" or key.endswith("_id") or key.endswith("_ids"):
        return "unbound_record_reference"
    return "legacy_record_identity"


def sanitize(value: Any, path: str, dropped: dict[str, int]) -> Any:
    """Copy only source and decision evidence; never copy a target identity."""
    if isinstance(value, str):
        if QA_DATABASE in value:
            raise ManifestError(f"QA database identity remains at {path}")
        if value == "create_qa_leaf":
            return "create_historical_leaf"
        if "create_qa_" in value.lower() or "-qa-" in value.lower() or "qa-only" in value.lower():
            raise ManifestError(f"QA-only value remains at {path}")
        return value
    if isinstance(value, list):
        return [sanitize(item, f"{path}[{index}]", dropped) for index, item in enumerate(value)]
    if not isinstance(value, dict):
        return value

    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key in RENAME:
            renamed = RENAME[key]
            if renamed in cleaned:
                raise ManifestError(f"duplicate renamed field at {path}: {renamed}")
            cleaned[renamed] = sanitize(item, f"{path}.{renamed}", dropped)
            category = removed_category(key)
            dropped[category] = dropped.get(category, 0) + 1
            continue
        if is_forbidden_key(key):
            # Record only the field name/count; do not preserve its QA value.
            category = removed_category(key)
            dropped[category] = dropped.get(category, 0) + 1
            continue
        cleaned[key] = sanitize(item, f"{path}.{key}", dropped)
    return cleaned


def assert_source_only(value: Any, path: str = "$") -> None:
    """Toxicity check run before any Odoo import or ORM interaction."""
    if isinstance(value, dict):
        for key, item in value.items():
            if is_forbidden_key(key) or key.startswith("decision_target_"):
                raise ManifestError(f"forbidden QA/target field remains at {path}.{key}")
            assert_source_only(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_source_only(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and (QA_DATABASE in value or "create_qa_" in value.lower() or "-qa-" in value.lower() or "qa-only" in value.lower()):
        raise ManifestError(f"QA identity remains at {path}")


def load_contract(path: Path, expected_archive: str) -> tuple[dict[str, Any], dict[str, int]]:
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"invalid JSON: {path}: {error}") from error
    if not isinstance(parsed, dict):
        raise ManifestError(f"contract root must be an object: {path}")
    archive_sha = str(parsed.get("source_archive_sha256", ""))
    if archive_sha and not SHA256_RE.fullmatch(archive_sha):
        raise ManifestError(f"source archive SHA is invalid: {path}")
    if not archive_sha:
        archive_sha = expected_archive
    if archive_sha.upper() != expected_archive.upper():
        raise ManifestError(f"source archive SHA differs: {path}")
    dropped: dict[str, int] = {}
    payload = sanitize(parsed, "$", dropped)
    assert_source_only(payload)
    return {
        "artifact_sha256": sha256_bytes(raw),
        "source_archive_sha256": archive_sha.upper(),
        "payload": payload,
    }, dropped


def build_manifest(inputs: list[Path], expected_archive: str) -> dict[str, Any]:
    if not inputs:
        raise ManifestError("at least one immutable decision artifact is required")
    if not SHA256_RE.fullmatch(expected_archive):
        raise ManifestError("expected source archive SHA is invalid")
    contracts: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    archives: set[str] = set()
    for input_path in inputs:
        if not input_path.is_file():
            raise ManifestError(f"missing immutable decision artifact: {input_path}")
        contract, local_dropped = load_contract(input_path, expected_archive)
        contracts.append(contract)
        archives.add(contract["source_archive_sha256"])
        for key, count in local_dropped.items():
            dropped[key] = dropped.get(key, 0) + count
    if len(archives) != 1:
        raise ManifestError("input artifacts do not share one source archive")
    result = {
        "schema": SCHEMA,
        "source_archive_sha256": next(iter(archives)),
        "contracts": contracts,
        "dropped_qa_fields": dict(sorted(dropped.items())),
        "runtime_rule": "source-only; target references must be rebound in the rehearsal database",
    }
    assert_source_only(result)
    return result


def render_manifest(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-archive-sha", required=True)
    parser.add_argument("--verify", action="store_true", help="validate an existing manifest without writing")
    args = parser.parse_args()
    try:
        if args.verify:
            parsed = json.loads(args.output.read_text(encoding="utf-8"))
            if parsed.get("schema") != SCHEMA:
                raise ManifestError("manifest schema differs")
            assert_source_only(parsed)
            print(json.dumps({"ok": True, "sha256": sha256_bytes(args.output.read_bytes())}))
            return 0
        manifest = build_manifest(args.input, args.source_archive_sha)
        rendered = render_manifest(manifest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(rendered)
        print(json.dumps({"ok": True, "sha256": sha256_bytes(rendered), "contracts": len(manifest["contracts"])}))
        return 0
    except (ManifestError, OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
