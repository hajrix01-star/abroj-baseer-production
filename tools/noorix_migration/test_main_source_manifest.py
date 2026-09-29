#!/usr/bin/env python3
"""Focused, no-ORM tests for the MAIN source-manifest boundary."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_main_source_manifest.py")
SPEC = importlib.util.spec_from_file_location("main_source_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
WRITER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WRITER)


class SourceManifestTests(unittest.TestCase):
    def payload(self) -> dict:
        return {
            "schema_version": 1,
            "target_database": WRITER.QA_DATABASE,
            "source_archive_sha256": "A" * 64,
            "company": {"source_company_id": "source-company", "target_company_id": 31},
            "documents": [{
                "source_invoice_id": "source-invoice",
                "source_total_raw": "115.0000",
                "target_partner_id": 88,
                "target_account_id": 99,
                "target_product_code": "NOORIX-HIST-FOOD",
                "target_account_code": "400001",
                "original_move_id": 456,
                "original_historical_salary_map_id": 57,
                "purchase_journal_id": 78,
                "run_name": "qa-run",
                "decision": "create_qa_leaf",
                "required_runtime_contract": "QA-only migration writer/model must create records",
            }],
        }

    def test_removes_all_target_identities_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "decision.json"
            source.write_text(json.dumps(self.payload()), encoding="utf-8")
            manifest = WRITER.build_manifest([source], "A" * 64)
        encoded = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn(WRITER.QA_DATABASE, encoded)
        self.assertNotIn("target_partner_id", encoded)
        self.assertNotIn("target_company_id", encoded)
        self.assertNotIn("original_move_id", encoded)
        self.assertNotIn("original_historical_salary_map_id", encoded)
        self.assertNotIn("purchase_journal_id", encoded)
        self.assertNotIn("run_name", encoded)
        self.assertNotIn("create_qa_", encoded.lower())
        self.assertNotIn("-qa-", encoded.lower())
        self.assertNotIn("qa-only", encoded.lower())
        row = manifest["contracts"][0]["payload"]["documents"][0]
        self.assertEqual(row["decision_product_code"], "NOORIX-HIST-FOOD")
        self.assertEqual(row["decision_account_code"], "400001")

    def test_toxicity_check_rejects_qA_database_and_target_identity(self) -> None:
        with self.assertRaises(WRITER.ManifestError):
            WRITER.assert_source_only({"target_company_id": 1})
        with self.assertRaises(WRITER.ManifestError):
            WRITER.assert_source_only({"note": WRITER.QA_DATABASE})
        with self.assertRaises(WRITER.ManifestError):
            WRITER.assert_source_only({"original_historical_salary_map_id": 57})
        with self.assertRaises(WRITER.ManifestError):
            WRITER.assert_source_only({"purchase_journal_id": 78})
        with self.assertRaises(WRITER.ManifestError):
            WRITER.assert_source_only({"note": "QA-only migration writer"})


if __name__ == "__main__":
    unittest.main()
