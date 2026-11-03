# PROCUREMENT-CART-CONSISTENCY-20261103

Base: official/main 51cb9203; deployed procurement source 50497529, v19.0.14.0.16.
Impact: LOCAL component behavior and Arabic labels; existing catalogue component -> company-scoped quote/receipt RPC remains unchanged. Architecture reference: docs/architecture/registry/INDEX.md PROCUREMENT-COMPACT-CART-20261103.
Confirmed defect predates latest layout: bbc8a6cb already contains zero -> remove(toggle) behavior. Do not attribute to the compact cart release.
Contract: new-cart zero removes on committed edit (allow typing 0.5); receipt zero marks not received; minus at zero does nothing; explicit restore restores last received quantity/price; increasing from zero restores price but increments quantity normally. Invalid/negative input remains rejected. Pending quotes cannot overwrite newer/empty-cart state. Receipt snapshot is browser-only, excluded from all explicit RPC payloads.
Scope: JS/XML/SCSS/Arabic translations/version and regression tests. No model/security/accounting/source-data edits. Reuse existing QA; no new load test or environment justified.
Validation: regression fails before fix, method tests incl decimal entry, zero/delete/restore, invalid entry, quote race, existing route tests; JS/XML/PO/SCSS validation; independent scoped delivery review; CI and protected QA deployment; QA browser desktop/narrow receipt and new-cart actions without business submission; protected production deployment only after QA acceptance.
User authorized repair, QA then production promotion in this chat. No separate manual build gates for this local repair under AGENTS.md.

Local evidence: six original tests passed and six new scenarios failed before fix. Final 14/14 passed, including blank-field receipt edit and quote races. JS syntax/diff checks pass; XML/SCSS/PO parsed using existing local Odoo container. Existing historical PO duplicate ids were detected; new strings are unique. Independent scoped reviewer closed P2 blank-field price restoration and gave QA-candidate GO pending CI/browser acceptance. No new test environment or load test.
