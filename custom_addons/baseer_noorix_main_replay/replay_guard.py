"""Non-writing safety boundary for the Noorix MAIN rehearsal replay.

This module deliberately contains no models and no ORM writes.  It is the
first vertical slice: prove that the only allowed runtime database and the
source-only manifest are correct before a financial replay writer exists.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from odoo.exceptions import UserError


REHEARSAL_DATABASE = "baseer_noorix_main_rehearsal_20260913"
PRODUCTION_DATABASE = "baseer_dev"
QA_DATABASE = "baseer_noorix_data_migration_qa_20260912"
SOURCE_ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
SOURCE_MANIFEST_SHA256 = "84afbe3fa32dcb2ba89bb52451db032f3675baf50d97b243d63f4b31c9201fa6"
SOURCE_MANIFEST_SCHEMA = "baseer-noorix-main-source-manifest/v1"
FORBIDDEN_FIELD_RE = re.compile(r"^(?:target_.*|original_.*|run(?:_.*)?)$")


def fail(message: str) -> None:
    raise UserError("Noorix MAIN rehearsal guard: %s" % message)


def _is_forbidden_field(key: str) -> bool:
    return (
        bool(FORBIDDEN_FIELD_RE.fullmatch(key))
        or ((key == "id" or key.endswith("_id") or key.endswith("_ids")) and not key.startswith("source_"))
    )


def _assert_source_only(value, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_forbidden_field(key) or key.startswith("decision_target_"):
                fail("forbidden QA/target field remains at %s.%s" % (path, key))
            _assert_source_only(item, "%s.%s" % (path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_source_only(item, "%s[%s]" % (path, index))
    elif isinstance(value, str) and (QA_DATABASE in value or "create_qa_" in value.lower() or "-qa-" in value.lower() or "qa-only" in value.lower()):
        fail("QA identity remains at %s" % path)


def assert_rehearsal_database(env) -> None:
    database = env.cr.dbname
    if database == PRODUCTION_DATABASE:
        fail("production database is permanently forbidden")
    if database == QA_DATABASE:
        fail("QA database is permanently forbidden")
    if database != REHEARSAL_DATABASE:
        fail("unexpected database %s" % database)


def load_source_manifest(path: str | Path) -> dict:
    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
        parsed = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail("cannot load source-only manifest: %s" % error)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_MANIFEST_SHA256:
        fail("source-only manifest SHA-256 differs")
    if parsed.get("schema") != SOURCE_MANIFEST_SCHEMA:
        fail("source-only manifest schema differs")
    if parsed.get("source_archive_sha256") != SOURCE_ARCHIVE_SHA256:
        fail("source archive SHA-256 differs")
    if not isinstance(parsed.get("contracts"), list) or not parsed["contracts"]:
        fail("source-only manifest has no contracts")
    _assert_source_only(parsed)
    return parsed


def preflight(env, path: str | Path) -> dict:
    """Validate database and manifest.  This function never writes ORM data."""
    assert_rehearsal_database(env)
    manifest = load_source_manifest(path)
    return {
        "database": env.cr.dbname,
        "source_archive_sha256": manifest["source_archive_sha256"],
        "manifest_sha256": SOURCE_MANIFEST_SHA256,
        "contracts": len(manifest["contracts"]),
        "orm_writes": 0,
    }
