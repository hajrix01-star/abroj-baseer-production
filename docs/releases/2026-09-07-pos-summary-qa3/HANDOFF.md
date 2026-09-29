# POS-S3 QA candidate — unified daily sales, single-step save, WhatsApp and DAY OFF

Module baseer_pos_summary19.0.1.2.0, QA database baseer_reports_qa_20260907 on http://127.0.0.1:18070. Main database/service unchanged. Exact source and evidence hashes: manifest.json alongside this file.

## User journey
One **Sales summaries** menu opens a paginated daily archive. Each company/date appears once; New opens the existing morning/evening cards. Reopening old or new dates reconstructs their independent original shifts in the same form, including after native transient cleanup. Original shift details remain reachable for audit, source documents, WhatsApp and individual draft correction.

**Save** saves and posts both shifts in one transaction. **Save and WhatsApp** performs the same action then opens WhatsApp Web with the combined-day text report. The employee selects a recipient and sends manually. Approved days offer Open WhatsApp again, without creating more documents. Missing historical shifts remain visibly missing; no zero sales are inferred. Mixed approval states remain explicit.

**DAY OFF** hides cards and customer metrics, displays inclusive From/To dates and the existing closure reasons Eid, Holiday, Maintenance and Other, plus reason details. Other requires text. Save confirms the original full-day closure, with no sales/ledger; at most366inclusive days. Closed dates appear with blank financial cells and are excluded from daily averages. Confirmed closure details permit the existing manager cancellation workflow. Cancelled sources disappear from the archive and cannot be replayed/shared as confirmed.

## Architecture delta
Original baseer.pos.summary/allocation and native POS order/session/payment/account.move remain money authority. Read-only SQL baseer.pos.day.archive groups source summaries by company/date and unions bounded full-day closure dates. Positive IDs derive from minimum summary ID; closed dates use bigint negative IDs. IDs are navigation keys, not permanent foreign keys. Native list action/type handles row opening and native header New opens the existing form; no new JavaScript or dependency.

Existing transient day entry is only a working/read-only snapshot. Private factories check original source ACL/company before using the in-process identity token for historical inactive-method slots. Normal inputs cannot supply the token, source links or approval state. Entry lock precedes existing summary locks, then company MVCC serialization; fresh creation and posting share an outer savepoint. Closure creation delegates all overlap/date/company checks to original closure code. PostgreSQL numeric/Decimal own sums, no frontend arithmetic. Scoped CSS only fixes archive mobile widths and readonly date hit target.

## Verified evidence
- pos_s3_checks.json:34 archive/reopening/permissions/atomic financial tests, final-source rerun passed.
- pos_s3_whatsapp_checks.json:24 Arabic/English URL/source-total/rollback/replay tests passed.
- pos_s3_day_off_checks.json:32 range/Other/overlap/SQLNULL/company/no-POS/denominator/vacuum/cancelled-source tests passed;366inclusive dates supported.
- pos_s3_concurrency.json:two independent real PostgreSQL serialization/retry cases: simultaneous new one-step saves and saved entry racing original approval. Exactly expected original records, no duplicate/deadlock. Zero fixtures avoid committed ledger; positive financial posting and late-second-failure rollback covered above.
- Actual mobile Save and WhatsApp created approved sources287/288 for2026-09-03:115cash/10customers and230bank/20customers; report345gross,45VAT,30customers,11.50average. Browser opened WhatsApp tab with encoded text; no Send click.
- Actual closure30 forSeptember1–2 saved from same form, confirmed and reopened by negative-ID date cell on mobile. No money shown on closed rows. Legacy pair227/228 reopened together345/30.
- Arabic/English desktop/mobile images; final380PO entries,0missing/0fuzzy. Native TranslationImporter overwrite applied only this addon; hard reload needed to refresh client language/assets. Arabic restored.
- Mobile archive measured390clientWidth/390scrollWidth, complete dates visible; native numeric display uses0–9.
- Final-source archive page measurement0.000626seconds on small QA fixtures; not a production capacity certificate. S2 limits25methods/card retained.

## Retained QA demonstrations / accounting audit
Original63account.move,147move lines,1POS order,3payments and3sessions all retain exact row hashes. The actual UI demonstration intentionally added4native moves,10lines,2orders,2payments and2sessions, all tied to sources287/288. Original approved82 remains1800/60; old draftpair227/228 remains345/30. New closure30 is clearly labelled a test example. All executable test fixtures rolled back or exact-cleaned; native UI examples remain for review.

ForSeptember1–7 the backend report now has2145approved sales/90customers over2operating days,2closed days and3missing days: daily means1072.50sales and45customers. Drafts and closures are not counted as completed sales days.

Main read-only verification:0moves,0lines,0installed baseer_pos_summary modules. No main upgrade, service restart or write performed.

## Recovery and entry points
Before-change QA DB: .local-backups/pos-summary-s3/database.dump SHA2562e386d0e53cc98b372debadb6a31d5e4ffdfcfe6cf3e03fdd77b125d9251e98c. Source-before.zip is QA2 archive SHA256ac34905a318bdfde7c950397dedcd5e3bc122c822082a84778066a3d94bc561d. Restore matching QA DB/source to roll back; do not uninstall financial records. No irreversible production operation is part of this candidate.

Unified list: http://127.0.0.1:18070/odoo/action-490
New entry: http://127.0.0.1:18070/odoo/action-497
Daily report: http://127.0.0.1:18070/odoo/action-496

Contract: docs/build-governance/POS-SUMMARY-S3.md. Independent final gate/delivery decision: POS-SUMMARY-S3-REVIEW.md in the same directory.
