# Chart committee — ERP integration and simplicity review

2026-09-08. Read-only review of the proposed chart/report arrangement. Role: ERP/Odoo integration; no chart, report, seed, or transaction changes authorized by this review. Prior approved CSS1/CAS1 evidence was reused; live accounting balances were not re-audited by this reviewer.

## Opinion

Keep the Saudi chart and its account codes. The proposed six headings are sensible as a **presentation arrangement** after a short implementation/acceptance cycle. They are not a ready-made configuration in the installed report, and should not be achieved by changing account codes or moving unrelated ledger groups.

Use the existing report's account totals and rendering framework. Add a small local extension of the P&L handler that assigns expense account IDs to company-owned presentation buckets; do not fork the vendor query engine or create a second financial ledger. Retain unmapped expenses visibly under Other Expenses and prohibit double membership. Report totals must reconcile exactly before and after grouping for identical company/date/posted/currency options.

## What the installed source actually supports

1. `third_party_addons/erp_heritage_19/eh_account_dynamic_reports/models/profit_and_loss.py:665` builds nature-based Income and Expenses from the existing account totals. Its hierarchy switch calls `_render_account_lines_grouped`.
2. `third_party_addons/erp_heritage_19/eh_account_base/models/report_handler_sectioned.py:1245` explicitly walks `account.account.group_id` and `account.group.parent_id`. This is native ledger group presentation, **not arbitrary explicit account sets for HR/utilities/etc.**
3. `odoo/addons/account/models/account_account.py:420` derives group membership from account code-prefix ranges. Scattered accounts such as leave tickets, insurance, visas and employee permits cannot be collected safely into one native prefix group while preserving all existing codes and intervening accounts.
4. There are explicit company account sets for finance cost, tax expense and deferred tax (`eh_account_base/models/res_company.py:215,250,269`; used by P&L by-function mode). They serve those specific purposes and should not be repurposed for HR headings.
5. CSS1 adds products/category mappings, not report presentation groups. `custom_addons/baseer_service_seed/models/catalog.py` confirms utilities 400018, telephone 400020, internet 400023, subscription 400045, license 400032 and legal/attestation 400031. Its new permit account must be resolved by the company's stable XML identity, not assumed always to be code 400093: the code allocator can choose another free code.

## Cash categories and P&L are different views

`custom_addons/baseer_cash_categories/models/cash_categories.py:300` starts with posted `asset_cash` movements in the selected period; `_trace` at line203 follows reconciliations to invoice evidence; `_path` at line136 groups the invoice product's category. It defaults to including VAT (`build_default_options`, line64). Thus it can split electricity and water through their product leaves even when both post to 400018, but it measures allocated **cash movement**, not all incurred utility expense.

The usual P&L path (`report_handler_sectioned.py:366`) sums income/expense ledger balances by accounting date. It also has a real `cash_basis` option, so labels and acceptance must explicitly specify which basis is selected. Even P&L with cash basis is not automatically identical to the cash-category report: the latter includes treasury movement outside P&L (for example asset advances) and can include invoice VAT.

Example: an electricity bill is posted in January and paid in February. Accrual P&L recognizes its expense in January; the cash-category report reflects the evidenced outgoing cash in February. This difference is expected, not a reconciliation error.

## Precise objections and refinements

- Keep 400018 as the existing combined utility ledger account if simplicity is the objective. Its electricity/water split is available in the cash-category report only for correctly categorized and traceable paid documents. If management later needs an **accrual** electricity/water split, that requires a separate product/category-based expense analysis; do not present the cash report as that analysis.
- Keep 400020 and 400023 distinct according to the approved service mapping. Existing historic uses of 400023 may include communication costs beyond internet; label the account accurately and do not silently reinterpret its full balance as internet-only.
- Account-level HR grouping is broad: 400075 means Other Employee Expenses, not exclusively issued HR service records. Name the heading accordingly or document that it includes all transactions posted to the selected accounts. Likewise 400031 may include broader legal costs, not merely attestations.
- Standardizing future use of similar accounts does not consolidate their old balances. Leave historical accounts visible in the appropriate bucket; archive only under an explicit reviewed decision, never as part of presentation seeding.
- Employee advances, payroll payables and prepaid expenses remain their native asset/liability types and existing reconciliation authorities. They do not belong in expense buckets merely because their cash recipient is an employee or service provider.
- Supplier default categories and the batch label `entry_type=expense` are entry conveniences. Ledger account/type and posted entries determine P&L; they are not controlled by the label.
- Keep all current journals. The proposed report headings require no per-heading or per-service journals.

## Smallest delivery path

**Priority decision after the committee discussion:** do not implement the custom
presentation immediately. First verify the accounting sources for cost of sales,
platform commissions, rent, payroll, advances and prepayments. POS sales summaries
and service-product purchase batches do not by themselves establish inventory
consumption/cost of sales; cleaner headings cannot correct a missing expense.
Use the installed native P&L and cash-category report with their explicit bases
during that review. The presentation extension is a subsequent convenience stage,
needed only if the six custom headings remain desired after source reconciliation.

Accept the accountant's broader heading **Licenses, Attestations and Legal Services**
instead of Government Fees when the group includes 400031 Legal Fees. A payment to
a private lawyer must not be relabeled as a government fee. Each account belongs
to exactly one display bucket, irrespective of overlapping HR/provider/category
labels in operational screens.

1. Approve a per-company mapping from existing account identities to the six display headings, including explicit Other Expenses coverage. Resolve ambiguous account purposes before seeding.
2. Implement a report-local presentation extension in `custom_addons`, retaining vendor queries, arithmetic, company security, currency treatment, comparisons, and native account drilldown. Initially limit it to the reviewed P&L presentation mode; do not alter unrelated Balance Sheet/Trial Balance hierarchies.
3. Verify original and regrouped totals on multiple months, unpaid and part-paid bills, reversals, adjustments, unclassified/new accounts, comparisons, screen/PDF/export and company switching. Verify each account appears once, and statutory/general-ledger output remains accessible.
4. Only then add fill-only presentation defaults to eligible new companies. Preserve existing chart/groups and manual mappings; resolve CSS1 purpose identities rather than matching names or cross-company numeric codes. CSS1 currently supports independent SAR companies; do not promise foreign-currency/branch presentation seeding without a separate contract.

Evidence reused: `docs/architecture/registry/INDEX.md`, `COMMON-SERVICES-SEED-GATE-REVIEW.md`, CSS1 accepted catalog source and the named narrow report paths. This is a design recommendation, not acceptance of an already implemented presentation feature.
