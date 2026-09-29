# SD2 — Independent G8 predeployment review

**GO** for controlled deployment of commit **`973395f87b62c8d09f1e6fdc301a7d89e2988d56`** only. Reviewer: `/root/payment_seed_review`, 2026-09-09. No blocking finding remains in this bounded candidate. MAIN deployment and its final preservation/runtime checks have not yet been executed by this reviewer.

## Candidate and running baseline

- Independently enumerated **1118** frozen source files and verified every SHA256 against `candidate.json`: zero mismatches or additional source files. Git HEAD is the stated candidate and the checkout is clean.
- Compared against accepted SD1 parent `2d2ff102d11a53fc2fca1b8c1707fc81c77537ab`: **1109 files unchanged; nine changed files all inside `custom_addons/baseer_sales_dashboard`**. No other addon or financial posting source changed.
- Verified archive SHA256 `7e22698e98d28b3b13a4eb786dc26397c8b697f324e3f36a171b24c63bf935d6`.
- Independently inspected current MAIN container and queried module state in a read-only transaction: MAIN still runs SD1 from its three read-only addon mounts, module `installed|19.0.1.0.0`, and zero pending module operations. Image is the unchanged pinned `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`. Candidate addon version is `19.0.1.1.0`.

## Accepted evidence

The contract and prior independent decisions are in `SALES-DASHBOARD-COMPACT.md` and `SALES-DASHBOARD-REVIEW.md`, through SD2-R08. Source review confirmed native filter semantics, bounded long-period aggregation using the existing daily authority, ratios of combined numerators, distinct recorded morning/evening/full-day scopes, and actual payment allocations with explicit missing/mismatched coverage. Payment totals are sales allocations, not bank/platform settlement balances. No customers or bill averages are invented per payment method.

- **75/75 backend checks passed**, and the copied release evidence matches frozen backend SHA256 `ea8827c554bca1c0e38d0dd722be54ad08a49957199e3f11510b1466bd1fddf1`. Checks cover native dates, open/all-time ranges, calendar limits, 367-day chunk boundaries, source/shift/payment totals, missing and zero states, protected source actions, company isolation, capacity guards and absence of source/ledger/transient writes. Test fixture rollback leaves zero tagged rows.
- **34/34 component checks passed**. Frozen component SHA256 `577dc666c29376e6cdf329879b7a28f9595ffe9328bd26b4d49c03dbbde2dfda` and both integration JS/XML hashes match the copied evidence. These checks use stubbed services/hooks/canvas; browser evidence supplies actual layout and interaction coverage.
- Reviewed `browser-evidence.md` and independently inspected final native Arabic filter, payment source list, mobile payment table, fresh English LTR and empty-year screenshots. Actual calendar selection preserves Western digits for March 1–August 31, the five established QA KPIs remain exact, and the combined chart has separately named sales/currency and customer/count axes. HungerStation drilldown opens the original 341-row allocation list after the explicit action-views fix. The 390px evidence shows wrapped names and no horizontal overflow. The empty-year illustration is explicitly labeled, has no numbered axes or sample financial values, and cards show dashes.
- The scoped filter subclasses and primary inherited range template change digit presentation and remount date inputs only. Native period options, callbacks and shared picker classes remain intact. Earlier screenshots precede the final date/source-action fixes; the final filter/source screenshots and matching test hashes specifically cover those fixes.

Local measured latency is 0.187082/0.262155/0.172550 seconds for ten years plus a prior ten-year range, with **7306 current summaries and zero previous summaries**, one reader and ORM cache invalidation. This is not a benchmark of two populated decades, 100 years or concurrent production load. The explicit calendar/source-count guards prevent silent truncation; no broader capacity claim is made.

The retained owner-requested QA demo is synthetic: 683 summaries and 3415 allocations, preserving the original 368 daily totals and native accounting/POS fingerprints. It is not actual receipts, inferred shifts in real business history, or a new posting certification. MAIN contains no preview transactions.

## Deployment and closure

Reviewed `../../build-governance/sales_dashboard_compact_release.py` against the accepted SD1 helper. It verifies the parent/source/archive, binds this decision to the candidate commit, requires installed SD1, stops MAIN for a coherent database/filestore backup, promotes immutable mounts and updates only this addon. Existing business-table projections must match before MAIN is restarted; failure leaves MAIN stopped for investigation and recovery from saved artifacts. No business seed or transaction migration is part of this release.

Proceed with the already authorized protected deployment. Close delivery only after retaining its actual backup, preservation and runtime evidence plus a read-only MAIN dashboard/native-navigation check. No fresh restoration drill or full ERP recertification is asserted. The reviewer changed review documents only.
