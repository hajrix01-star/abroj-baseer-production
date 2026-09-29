# Native summary card — QA4

Version19.0.1.2.1 adds a Sales summary card to the native POS dashboard for the active company's existing dedicated configuration. Enter summary opens the existing morning/evening/DAY OFF form; Saved summaries opens that company's daily archive. Ordinary cashier cards retain their native behavior. Companies without an active dedicated configuration do not show a summary card.

Only configuration model, inherited configuration view, version and Arabic dictionary differ from QA3. No new dependency, JavaScript, schema or financial engine change. Access/company guards apply to navigation, existing posting remains authoritative. QA only: http://127.0.0.1:18070/odoo/point-of-sale. Main not changed.

Validation: successful module upgrade, 25 rollback-only route/security/domain/default checks, actual desktop/mobile card and both navigation buttons. Arabic source386 terms no missing/fuzzy; English canonical source preserved. Native cashier session not opened/closed by this change. Query assumptions inherited from S3; no production capacity claim.

Exact source/evidence hashes in manifest.json. Recovery: prior source .local-backups/pos-summary-s4/source-before.zip and pre-upgrade QA database.dump. Restoring prior source requires QA module upgrade to restore old dashboard domain/view state; for exact rollback restore both QA database and source. Do not restore over main. Browser may retain old action/view cache; open a fresh tab after upgrade.

Architecture delta: reuse existing unique company pos.config as native card; guarded read-only action navigation, no data authority change. Independent gate and final delivery decision: docs/build-governance/POS-SUMMARY-S4-REVIEW.md.
