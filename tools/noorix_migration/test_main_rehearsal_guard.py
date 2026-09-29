#!/usr/bin/env python3
"""Focused pure tests for the MAIN rehearsal boundary; no Odoo ORM needed."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import unittest
from pathlib import Path


GUARD = Path("custom_addons/baseer_noorix_main_replay/replay_guard.py")
SOURCE = GUARD.read_text(encoding="utf-8")


class RehearsalGuardBoundaryTests(unittest.TestCase):
    def test_database_allowlist_is_exact_and_production_is_explicitly_forbidden(self) -> None:
        self.assertIn('REHEARSAL_DATABASE = "baseer_noorix_main_rehearsal_20260913"', SOURCE)
        self.assertIn('PRODUCTION_DATABASE = "baseer_dev"', SOURCE)
        self.assertIn('QA_DATABASE = "baseer_noorix_data_migration_qa_20260912"', SOURCE)
        self.assertIn('if database != REHEARSAL_DATABASE:', SOURCE)

    def test_manifest_boundary_rejects_qa_fields_before_orm_calls(self) -> None:
        for field in ("target_.*", "original_.*", "run(?:_.*)?", "key.endswith(\"_id\")"):
            self.assertIn(field, SOURCE)
        self.assertIn("_assert_source_only(parsed)", SOURCE)
        tree = ast.parse(SOURCE)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertFalse(any(call.func.attr in {"create", "write", "unlink"} for call in calls))

    def test_current_manifest_hash_matches_pinned_guard(self) -> None:
        manifest = Path("outputs/01a0926b-3b31-75f2-9e93-1679ceaef536/noorix-main-replay/source-manifest.json")
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        pinned = re.search(r'SOURCE_MANIFEST_SHA256 = "([0-9a-f]{64})"', SOURCE)
        self.assertIsNotNone(pinned)
        self.assertEqual(digest, pinned.group(1))
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("baseer_noorix_data_migration_qa_20260912", encoded)
        self.assertNotIn('"target_', encoded)


if __name__ == "__main__":
    unittest.main()
