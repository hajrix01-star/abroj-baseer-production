# FL2 independent cash preview review

Decision: GO — QA preview only. No MAIN or GitHub publication approval.

Reviewer: icons_release. Baseline: FL1 frozen source 0a6246b7215caddf9e7b14ffe799f84ee03f8cd3. Review is limited to the existing financial register addon delta; the accepted cash-category allocation engine, native Odoo core and AR2 permissions remain unchanged. Reviewer made no application edits or environment mutations.

## Source and accounting authority

The register adapter inherits the existing cash handler's final `_payload` hook. It captures accepted VAT-inclusive Decimal movement fragments after the original tracing, signed allocation, same-period transfer exclusion and ledger reconciliation. Cash-source AMLs and their moves receive explicit caller read checks. A private method-local dictionary enables capture; client context does not carry the capture object or authoritative values. No sudo, new ACL, EH report group, posting logic or stored transaction data is added.

Rows regroup the original fragments by cash-source journal entry and direction. Receipts plus signed payments equals each row's net. Before exposure, all three sums must exactly equal the reference report's `meta.exact_totals`; mismatch fails closed. KPIs intersect these bounded contributors with current native move search rules and facets. The existing handler keeps AML/counterpart access rules and fails on inconsistent visible counterpart balances. Native money fields convert only at the display boundary; KPI strings use the existing currency formatter.

Cash action and endpoints enforce the accepted register accounting gate, excluding cashier. A validated calendar month and one active authorized SAR company define the report. Company membership and SAR policy remain enforced by the existing handler. The search predicate reconstructs report contributors each time; no browser-supplied ID snapshot becomes authority. Reading arbitrary hidden payroll entries still uses native privacy rules. The visibility and nonzero search helpers also explicitly enforce feature access before handling operators.

## Native UI integration

Primary inherited native list/kanban views replace invoice money/status columns only for cash mode. They retain source navigation, paging and the shared KPI component. The cash search offers reference, partner, journal and direction facets; the toolbar owns the calendar-month scope without a second preset date selector. Three cards replace the existing invoice cards in the same area. All-mode action removes the cash-month marker. Mode navigation is guarded against duplicate requests and destruction; invalid/failed month navigation restores the current value and exposes an error. Existing KeepLast and domain/context snapshot guards remain.

## Evidence reviewed so far

`fl2-cash-checks.json`: PASS63 on isolated `baseer_ar1_fl1_clean_20260910`, rollback=true, modules_preserved=true, commit_guard=true; recorded before/after native fixture counts match. Actual reference-report totals are the oracle. Coverage includes 8000.00 receipts / -5000.00 payments / 3000.00 net, row/card equality, arbitrary facets, draft/cancelled/unpaid exclusion, internal transfers, native partial settlement and reversal, mixed zero-net external movement, accountant/owner payroll privacy and malformed/forged/cashier gates. One-reader small-fixture calls measured14.9–71.839ms; no large-ledger or concurrent capacity claim.

`fl2-ui/frontend-checks.json`: PASS13 isolated mocked-hook/service assertions for endpoint selection, server company display, mode/month action arguments, duplicate navigation, invalid input, failed navigation and destruction. It also verifies return to All restores the native header-selected company IDs without mutating cash context. The `user.activeCompanies` API was checked against local native Odoo source.

Actual browser files reviewed: `cash-february-ar.txt/png` shows two rows and exact8000/-5000/3000; `cash-payments-filter-ar.txt` shows one payment row and matching narrowed cards; `return-all-ar.txt` shows invoice cards again and no cash-month input; `source-entry.txt` opens the native balanced5000 debit/credit entry. Reviewer visually inspected `cash-480-ar.png`: native kanban, same three cards in a responsive two-column grid, no visible overflow; parent measured document scroll width480 at480px. Arabic card/toolbar labels and Western money digits are present. The final replacement narrow screenshot and DOM were inspected again: all three cash row labels are now Arabic; the earlier untranslated literals are resolved.

FL2-R01 resolved: cash-to-All originally retained the single-company cash context. The frontend now copies context and restores `user.activeCompanies` IDs for the All action; server authorization remains unchanged. FL2-R02 resolved: three cash kanban literal translations were corrected and verified in the actual final mobile DOM and image, with no financial calculation impact.

## Final source binding and scope

Every file in `fl2-ui/source-hashes.json` was independently rehashed and matched current source. Inventory SHA256: `22c99d9bb2a5151adb296bdd4405cb052a0139567b859504a22c6d01dabc2c54`. Eleven addon files: two unchanged versus frozen FL1, eight modified and one added. The added cash adapter SHA256 is `5cb439ab5e80362df45744d51f0a651496c14252d154fab11ffe17214f16c990`; it includes explicit entry guards on both search helpers. Parent confirmed final PASS63 evidence was generated after that guard patch. Accounting evidence SHA256: `267a123a1e8e085c590d1f419076b53dbfae46648201ff95a58b54b9093e1094`.

Changed paths under `custom_addons/baseer_financial_register`: `__manifest__.py`, `i18n/ar.po`, `models/__init__.py`, `models/cash_register.py` (new), `models/financial_register.py`, `static/src/financial_register.js`, `static/src/financial_register.scss`, `static/src/financial_register.xml`, `views/financial_register_views.xml`. Exact individual hashes are retained in the verified inventory.

No open scoped blocker remains. GO permits showing the QA experiment described in `fl2-ui/PREVIEW.md`; it does not authorize production publication. No release helper, frozen FL2 candidate or deployment is part of this experiment. English source labels and mocked mode behavior are reviewed; no separate full English browser journey or browser race/concurrency test is claimed. Existing frozen FL1 and production/GitHub publication remain outside this review and were not mutated by the reviewer.
