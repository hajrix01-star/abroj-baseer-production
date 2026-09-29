#!/usr/bin/env python3
"""Prove the MAIN vault decisions cover exactly the active source use."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


MANIFEST = Path(
    "outputs/01a0926b-3b31-75f2-9e93-1679ceaef536/"
    "noorix-main-replay/source-manifest.json"
)


def active_source_vaults(value) -> set[tuple[str, str]]:
    """Collect document/record vault identities, not the decisions themselves."""
    found: set[tuple[str, str]] = set()
    if isinstance(value, list):
        for item in value:
            found.update(active_source_vaults(item))
        return found
    if not isinstance(value, dict):
        return found
    if "source_vault_id" in value and "source_company_id" in value:
        found.add((value["source_company_id"], value["source_vault_id"]))
    for key, item in value.items():
        if key != "vault_decisions":
            found.update(active_source_vaults(item))
    return found


class MainVaultDecisionCoverageTests(unittest.TestCase):
    def test_active_source_vaults_match_decisions_exactly(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        payloads = [contract["payload"] for contract in manifest["contracts"]]
        required = set()
        decisions = set()
        for payload in payloads:
            required.update(active_source_vaults(payload))
            for decision in payload.get("vault_decisions", []):
                decisions.add((decision["source_company_id"], decision["source_vault_id"]))
        self.assertEqual(required, decisions)


if __name__ == "__main__":
    unittest.main()
