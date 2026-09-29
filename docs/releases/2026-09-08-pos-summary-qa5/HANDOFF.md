# S5 lifecycle candidate — QA only

19.0.1.3.0 adds manager Archive/Unarchive and Delete drafts to the unified sales entry/archive. A draft day's morning/evening sources delete atomically or neither; batches containing approved/mixed/confirmed-closure rows are rejected. Confirmation is visible on desktop/mobile. Approved sales and DAY OFF can be archived/restored; archival never removes financial or operating-day evidence. The new is_archived flag is presentation metadata, not Odoo active; reports and overlap checks continue to include sources. Normal list uses removable Not archived filter. Archiving a DAY OFF date archives its whole source closure range.

Native cashier rights remain exactly as-is per latest explicit user choice: no custom role, ACL/group assignments or posting privilege changes. Native POS users retain their existing reports; this release does not claim input-only isolation. Lifecycle buttons require POS manager server-side as well as in UI. Existing native source draft unlink permissions remain unchanged.

Validation:40 focused lifecycle+90 regression checks, rollback fixtures, preserved account.move/line fingerprints. Actual Arabic desktop/mobile archive/restore/delete journey used only new QA test sources310/311 (both deleted after test; no financial posting). Final form archive/restore uses native reload.400 translated terms, zero missing/fuzzy. UI screenshots, tests and exact source hashes in manifest.json.

No taxes, catalogue prices, previous invoices or accounting defaults changed. Native company tax-price setting is locked by existing accounting lines; prospective native tax overrides are available. Tax scope and meaning of closed-record deletion remain pending user clarification, outside this candidate's GO. Closed confirmed sources are not deleted.

Recovery: .local-backups/pos-summary-s5/source-before.zip is frozen QA4; database.dump is pre-S5 QA backup. Restore both to a QA environment for exact rollback. No main-environment mutation authorized or performed. Runtime http://127.0.0.1:18070, database baseer_reports_qa_20260907. Old browser tabs may cache action/views; reload from a fresh tab.

Architecture delta: two durable presentation flags and one SQL projected flag; guarded whole-day lifecycle delegates existing original source methods. No new business model, JS, dependency or financial calculation. Gate/delivery record docs/build-governance/POS-SUMMARY-S5-REVIEW.md. Pending user decisions are not hidden by this limited delivery.
