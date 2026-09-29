# CSS1 — Independent G0–G3 accounting/ERP gate review

2026-09-08. Reviewer: services_accounting_advice agent. Design review only; not a financial audit or release acceptance. Ownership limited to this document; other agents own implementation and other artifacts.

## Decision

**G0 GO; G1 GO; G2 GO; G3 GO for the seed scope in COMMON-SERVICES-SEED.md**, with the implementation requirements below incorporated into acceptance. The parent confirmed separate leaf categories and one default product per selectable service, separate iqama issuance/renewal leaves, and no supplier default for multi-service entities. No further user approval is required for these routine implementation choices. This is not G8 approval and does not certify the unimplemented HR service workflow or installed report behavior.

## Evidence reviewed

- `COMMON-SERVICES-SEED.md`, approved seed scope and capacity assumptions.
- `COMMON-SERVICE-PARTIES-SEED-DECISIONS.md`: 20 named parties, 3 source-backed VAT numbers, 17 unknown/blank, approved HR service list, one visa product and no final-exit service.
- `custom_addons/baseer_company_setup/models/company.py`: company precommit callback, chart callback, row locking, root-company scope, Saudi XMLID account reuse and fill-only setup.
- `custom_addons/baseer_purchase_batch/models/purchase_batch.py:102`: UNIQUE(company_id, category_id), one default product, service/category/company/account validation.
- `custom_addons/baseer_purchase_batch/models/res_partner.py`: company-dependent supplier category is a suggestion, not an accounting authority.
- Existing actual account snapshot `hr_services_current_accounts_review.json`, native Saudi account template and reporting discussion.

## Gate findings

| Gate | Result | Basis / acceptance boundary |
|---|---|---|
| G0 | GO | Authorized reusable company seed only; QA only; no posted/draft financial or HR transactions. Existing master-data choices preserved. Financial source of truth remains native accounting. |
| G1 | GO | 100 roots, 20 contacts, under 50 service products per root and 2 concurrent calls are explicit assumptions. Measure one new-company seed under 15 seconds and repeat/concurrent execution in isolated QA. This is a measurement target, not an unmeasured throughput promise. |
| G2 | GO | Native models with stable per-company identities and existing row lock; one leaf/default product per batch-selectable service. Verify all records/account links in the owning company, preserve archived/custom settings, and avoid historical category edits. |
| G3 | GO | Existing Odoo 19 ORM, categories, contacts, products and batch mapper are the direct path. No new frontend/runtime/library, no native/vendor-source edits, no new monetary calculations. |

## Approved leaf/account mapping guidance

Reuse `account.<company_id>_sa_account_<code>` only where its ownership, active status and expense type are valid. A missing safe target may create one dedicated account per economic purpose with a collision-safe code and stable seed identity. Similar service variants share the appropriate account, not a new account per product or supplier.

| Proposed category path / leaf | Account purpose / Saudi target |
|---|---|
| خدمات الموظفين / الإقامات وتصاريح العمل / إصدار إقامة | Dedicated iqama/work-permit expense account; no explicitly named existing Saudi account found in the actual snapshot. |
| Same parent / تجديد إقامة | Same iqama/work-permit expense account. |
| Same parent / إصدار رخصة عمل | Same iqama/work-permit expense account. |
| Same parent / تجديد رخصة عمل | Same iqama/work-permit expense account. |
| Same parent / نقل خدمات الموظف | Same dedicated administrative employee permit/service purpose, if the leaf denotes the administrative fee itself. |
| Same parent / تعديل المهنة | Same dedicated administrative employee permit/service purpose. |
| خدمات الموظفين / التأشيرات / تأشيرات | 400014 Visa Expenses; exactly one default product. Issue/extend exit-and-return is the later HR service detail, not separate seeded visa products. No final exit. |
| خدمات الموظفين / الشهادات والفحوص / إصدار شهادة صحية | 400075 Other Employee Expenses. |
| Same parent / تجديد شهادة صحية | 400075. |
| Same parent / فحص طبي | 400075; do not label a medical examination as insurance. |
| خدمات الموظفين / التذاكر / تذكرة سفر | 400006 Leave Ticket for the employee-service benefit. Generic business travel 400024 is not interchangeable by supplier name. |
| خدمات الموظفين / التأمين الطبي / إصدار تأمين طبي | 400009 Medical Insurance for recognized expense; no assertion that the whole annual policy is immediately expensed. |
| Same parent / تجديد تأمين طبي | 400009, same limitation. |
| خدمات الموظفين / خدمات مساندة / خدمات تعقيب | 400075 for employee-service processing support; general legal/professional services have separate purposes. |
| Same parent / خدمة أخرى | 400075 as explicit employee-service expense, not every payment to a government entity. |
| المرافق / الكهرباء | 400018 Water & Electricity. |
| المرافق / المياه والصرف الصحي | 400018; cash-category report can distinguish leaves despite shared GL account. |
| الاتصالات والإنترنت / الاتصالات | 400020 Telephone. |
| الاتصالات والإنترنت / الإنترنت | 400023 Others - Communication, explicitly confirmed mapping; do not alternate with 400020 automatically. |
| الرسوم والخدمات الحكومية / الرخص البلدية | 400032 Trade License Fees, for the license fee itself. |
| الرسوم والخدمات الحكومية / السجل التجاري | 400032 Trade License Fees, for the commercial-registration service fee. |
| الرسوم والخدمات الحكومية / التصديقات | 400031 Legal fees, for the authentication service fee. |
| الرسوم والخدمات الحكومية / الخدمات العدلية | 400031 Legal fees, for the legal service fee; not every transfer to a justice-related entity. |
| اشتراكات المنصات / اشتراك قوى | 400045 Subscriptions, only for the subscription and not underlying permits or visa fees. |
| اشتراكات المنصات / اشتراك مدد | 400045 Subscriptions. |
| اشتراكات المنصات / اشتراك مقيم | 400045 Subscriptions. |

A supported SAR company with a generic chart keeps its chart. Create only dedicated expense accounts for the same selected purposes when needed; do not send all services to 600000, load the Saudi chart over it, or reuse numeric codes without company-scoped ownership validation. Expense accounts can be shared across service variants within that company. Actual QA company 1 is USD/US and is skipped by the currency amendment below, rather than used as the generic-chart fixture.

## Required implementation safeguards

1. `baseer.purchase.category.map` is one product per company/category. Independent issuance/renewal choices require independent leaves; structural parents need no mapper. Additional variants in the same leaf must not be presented as separately selectable batch choices.
2. XMLID-owned global category/tag hierarchy is created once with noupdate behavior. Existing live product categories, names and parent links are not moved. Product-category changes would alter historical cash-report classification.
3. Repeated seeding preserves custom/archived native records and references. Search identities with `active_test=False`; never recreate/reactivate an archived choice. Invalid ownership/model identities must fail clearly rather than bind another company. Preserve an existing unique company/category mapping instead of overwriting it.
4. Product expense links are company-specific. New service products are company-private; globally shared category properties must not accidentally overwrite another company's defaults. No customer sale product by default unless separately intended.
5. Supplier tags are for filtering. Multi-service ministries/platforms receive no forced default expense category. GOSI/ZATCA receive tags/contact details only; no default expense, tax, salary deduction, or arbitrary service product representing a payment to them. Platform brand and legal invoice issuer remain distinguishable.
6. Do not blanket-assign 15% VAT to government services, or interpret a blank VAT number as exempt/unregistered. Only 3 party VAT values in the approved evidence are filled; preserve existing nonempty VAT. Product tax defaults must not silently mark all seeded government services taxable via ORM defaults.
7. Prepaid insurance 104021, employee receivables and refundable deposits are asset treatments and **must not be batch expense mappings**. The batch validator requires expense types. This seed does not implement amortization or change the current purchase workflow to support those treatments.
8. Extend the existing accounting hook after super with the same root-company row lock and scoped context. Handle nested chart-load callbacks/retry idempotently. Global category data must exist before the initializer runs. No commits inside the seed or one-off process bypass.
9. Native purchase/bank/cash journals already exist in reviewed QA companies; no new per-service journals. No account.group code-range creation or report behavior claim in this seed.
10. Validate no financial transactions changed; counts alone are insufficient for preservation of earlier records. Validate company isolation, new SA/SAR and SAR generic-chart companies, non-SAR no-op, two concurrent calls, repeat after rename/archive, and configured mapping preservation. G8 requires independent acceptance on actual results.

## Residual limits to report at delivery

The result is prepared contacts, service categories/products and expense mappings. Employee service issuance, visa detail entry, financial-record links, renewals, vendor bills/payments, prepaid-expense workflow and a dedicated P&L services heading remain outside this seed release. Global category and supplier-tag trees aid navigation; they are not account-group trees or tax policies.

## G2 reopened — user direction: service rows are expenses

2026-09-08. User directs that these services generally belong to the Expense label rather than Purchase. **G2 GO for a default/suggestion-only addon extension**, subject to the conditions below. Existing native field `baseer.purchase.batch.line.entry_type` is `purchase/expense`, default purchase, and is consumed as the printed row label (`purchase_batch.py:390,419`). Expense account selection is independently validated through the category product; this change does not alter a GL account, move type or tax treatment.

- For new rows whose resolved category belongs to this seed, use `expense` only if `entry_type` was not explicitly provided. Run the choice after native normalization resolves a supplier's default category; explicit category and supplier-inferred category should behave consistently.
- Recognize owned seed categories by stable identity, never translated names. Existing company/category/account authorization remains intact.
- Choosing a seeded service category in an editable row suggests Expense through normal onchange. The user can change the type to Purchase **after selecting the category** and that explicit submitted value is preserved. Choosing a seeded category again can suggest Expense again. No separate state field/widget or memory of the user's earlier UI choice is promised. No write hook that overwrites saved entries; no historical backfill.
- The parent's clarified contract explicitly accepts that normal category onchange behavior. A value equal to the native default `purchase` does not itself distinguish a previous explicit UI choice, so the guarantee is on the final submitted type, not preservation across another category selection.
- Required focused validation: missing type + explicit seed category defaults to Expense; missing type + supplier-inferred seed category defaults to Expense; explicit submitted Purchase remains Purchase; explicit Expense remains Expense; nonseed categories retain existing defaults; category onchange proposes Expense and a subsequent manual Purchase selection persists on saving; saved/posted records remain unchanged without explicit editing. Test actual UI payload because Odoo may send the default Purchase even where the user did not touch the type.

**Final reopened G2 decision: GO under this clarified contract.** Normal category onchange may suggest Expense each time a seeded service category is selected; backend normalization must preserve the final explicit type. A failure of those checks must be corrected before G8.

### Catalog completeness clarification

The parent confirmed four previously approved government-service leaves: municipal licenses and commercial registration to 400032, authentications and justice/legal service fees to 400031. Internet uses the deliberately selected 400023. Platform subscriptions are exactly Qiwa, Mudad and Muqeem. Balady remains a multi-service party and is not assumed to sell a uniform subscription. These mappings classify the explicitly named service fee, not supplier balances, deposits, tax remittances or all charges issued through a portal. **G2 GO includes this clarified catalog.**

### G2 compatibility amendment — SAR companies only

The actual batch dependency explicitly rejects non-SAR company records in `company_scope` (`custom_addons/baseer_purchase_batch/models/purchase_batch.py:41–47`). Creating category mappings for USD company 1 would fail initialization. The parent confirmed that actual company 1 is generic_coa/USD/US. **G2 GO with this required compatibility guard:** seed company-private CSS1 data only for independent root companies with an initialized chart and SAR currency. Skip non-SAR companies cleanly without changing their contacts, products, accounts, currency, country or chart; shared global category/tag definitions may remain available as native shared metadata. Preserve parent CAS1 behavior, but make the CSS1 extension itself a no-op for unsupported currency.

The generic-chart test uses a new isolated **SAR** generic-chart company. Do not alter company 1 to manufacture eligibility. Verify the five supported Saudi QA companies receive the complete seed, the USD company receives no CSS1 company-private records, and creating or initializing another non-SAR company does not fail because of this addon. The capacity assumption is 100 supported SAR root companies. This is a necessary existing-dependency boundary, not a loss of the requested Saudi-company coverage.
