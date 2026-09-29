"""Source and target safety boundary for the isolated Noorix rehearsal."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from odoo.exceptions import UserError


REHEARSAL_DATABASE = "baseer_integrated_release_rehearsal_20260914"
PRODUCTION_DATABASE = "baseer_dev"
QA_DATABASE = "baseer_noorix_data_migration_qa_20260912"
SOURCE_ARCHIVE_SHA256 = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2"
SOURCE_MANIFEST_SHA256 = "84afbe3fa32dcb2ba89bb52451db032f3675baf50d97b243d63f4b31c9201fa6"
SOURCE_MANIFEST_SCHEMA = "baseer-noorix-main-source-manifest/v1"
DEFAULT_MANIFEST_PATH = "/mnt/noorix-source/source-manifest.json"
SOURCE_VAULT_SNAPSHOT_SHA256 = "11538ed7a7f72f9e1e2dfbfb635cfcc91f5296e357284de0d7a7beea2a510a58"
DEFAULT_VAULT_SNAPSHOT_PATH = "/mnt/noorix-source/vault-source-snapshot.json"
HR_PAYROLL_SOURCE_SNAPSHOT_SHA256 = "48FDFC8BC82FDC89F652C093CCDB442C70467444EE939B90D8C0A3A9589504EC"
DEFAULT_HR_PAYROLL_SOURCE_SNAPSHOT_PATH = "/mnt/noorix-source/hr-payroll-source-snapshot.json"
FORBIDDEN_FIELD_RE = re.compile(r"^(?:target_.*|original_.*|run(?:_.*)?)$")


def fail(message: str) -> None:
    raise UserError("Noorix 18084 rehearsal guard: %s" % message)


def _forbidden_key(key: str) -> bool:
    return (
        bool(FORBIDDEN_FIELD_RE.fullmatch(key))
        or ((key == "id" or key.endswith("_id") or key.endswith("_ids")) and not key.startswith("source_"))
    )


def _assert_source_only(value, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _forbidden_key(key) or key.startswith("decision_target_"):
                fail("forbidden QA/target field remains at %s.%s" % (path, key))
            _assert_source_only(item, "%s.%s" % (path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_source_only(item, "%s[%s]" % (path, index))
    elif isinstance(value, str) and (
        QA_DATABASE in value or "create_qa_" in value.lower() or "-qa-" in value.lower() or "qa-only" in value.lower()
    ):
        fail("QA identity remains at %s" % path)


def assert_rehearsal_database(env) -> None:
    database = env.cr.dbname
    if database in {PRODUCTION_DATABASE, QA_DATABASE}:
        fail("production and QA databases are permanently forbidden")
    if database != REHEARSAL_DATABASE:
        fail("unexpected database %s" % database)


def load_source_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> dict:
    try:
        raw = Path(path).read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail("cannot load source-only manifest: %s" % error)
    if hashlib.sha256(raw).hexdigest() != SOURCE_MANIFEST_SHA256:
        fail("source-only manifest SHA-256 differs")
    if manifest.get("schema") != SOURCE_MANIFEST_SCHEMA:
        fail("source-only manifest schema differs")
    if manifest.get("source_archive_sha256") != SOURCE_ARCHIVE_SHA256:
        fail("source archive SHA-256 differs")
    if not isinstance(manifest.get("contracts"), list) or len(manifest["contracts"]) != 26:
        fail("source-only manifest contract count differs")
    _assert_source_only(manifest)
    return manifest


def load_vault_snapshot(path: str | Path = DEFAULT_VAULT_SNAPSHOT_PATH) -> dict:
    """Load the source-only raw vault receipt required for financial routing."""
    try:
        raw = Path(path).read_bytes()
        snapshot = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail("cannot load source-only vault snapshot: %s" % error)
    if hashlib.sha256(raw).hexdigest() != SOURCE_VAULT_SNAPSHOT_SHA256:
        fail("source-only vault snapshot SHA-256 differs")
    if snapshot.get("schema_version") != 1:
        fail("source-only vault snapshot schema differs")
    if snapshot.get("source_archive_sha256") != SOURCE_ARCHIVE_SHA256:
        fail("source-only vault snapshot archive differs")
    if snapshot.get("parent_manifest_sha256") != SOURCE_MANIFEST_SHA256:
        fail("source-only vault snapshot parent manifest differs")
    rows = snapshot.get("vault_source_rows")
    if not isinstance(rows, list) or len(rows) != 14:
        fail("source-only vault snapshot row count differs")
    identities = {(row.get("source_company_id"), row.get("source_vault_id")) for row in rows}
    if len(identities) != 14 or any(not row.get("source_row_sha256") for row in rows):
        fail("source-only vault snapshot identities differ")
    _assert_source_only(snapshot)
    return snapshot


def load_hr_payroll_source_snapshot(
    path: str | Path = DEFAULT_HR_PAYROLL_SOURCE_SNAPSHOT_PATH,
) -> dict:
    """Load the sealed, row-level payroll/HR evidence extracted from Noorix.

    The embedded evidence intentionally preserves raw Noorix columns such as
    ``id`` beneath ``source_evidence``.  It therefore cannot use the generic
    manifest key filter, which correctly rejects target-looking IDs elsewhere.
    Its own caller must instead accept only the documented group/row schema.
    """
    try:
        raw = Path(path).read_bytes()
        snapshot = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        fail("cannot load sealed HR/payroll source snapshot: %s" % error)
    if hashlib.sha256(raw).hexdigest().upper() != HR_PAYROLL_SOURCE_SNAPSHOT_SHA256:
        fail("sealed HR/payroll source snapshot SHA-256 differs")
    if snapshot.get("schema_version") != 1:
        fail("sealed HR/payroll source snapshot schema differs")
    if snapshot.get("source_archive", {}).get("sha256") != SOURCE_ARCHIVE_SHA256:
        fail("sealed HR/payroll source snapshot archive differs")
    if snapshot.get("parent_manifest", {}).get("sha256") != SOURCE_MANIFEST_SHA256:
        fail("sealed HR/payroll source snapshot parent manifest differs")
    groups = snapshot.get("groups")
    if not isinstance(groups, list) or len(groups) != 3:
        fail("sealed HR/payroll source snapshot group count differs")
    if any(QA_DATABASE in str(item) or PRODUCTION_DATABASE in str(item) for item in groups):
        fail("sealed HR/payroll source snapshot contains a forbidden target reference")
    return snapshot
