# M1 source, hooks and migration audit

2026-09-08. Independent bounded source audit of the candidate named in `MAIN-PROMOTION.md`. **Source gate: no blocking install-time data mutation found; proceed to the main-clone rehearsal, subject to the configuration and scope notes below.** This is not a cutover approval. No database, application source, settings or services were changed by this audit. Source hashes and before/after database fingerprints belong to the lead's separate evidence.

## Selected dependencies and install effects

| Candidate | Declared dependencies | Install/upgrade effects observed |
|---|---|---|
| `baseer_purchase_batch` 19.0.1.2.2 | `account`, `baseer_report_layout`, `baseer_category_display` | New batch/line/category mapping tables, company-dependent supplier preference, native ACL/rules/views/report, one shared `PB/year/` administrative sequence. No suppliers, products, categories, mappings, bills or payments seeded. |
| `baseer_category_display` 19.0.1.0.0 | `product` | Changes computed category display label globally to leaf name; explicit `hierarchical_naming` context retains native hierarchy. Does not rename categories or change parent relationships. |
| `baseer_pos_summary` 19.0.1.3.1 | `point_of_sale`, `baseer_cash_categories` | Adds summary/allocation/closure/entry/report models, fields on native POS records, unique constraints, ACL/rules/views/actions and a read-only daily SQL view. No config, product, payment category/method, tax, summary, closure, order, session or ledger seed. Also extends cash-report evidence handling; see below. |
| `baseer_report_layout` 19.0.1.1.1 | `eh_account_dynamic_reports` | QWeb inheritance, compact report assets and local IBM Plex Arabic font styling for selected Arabic PDFs. No Python models or accounting writes. Font files and license are present. |
| `baseer_web_navigation` 19.0.1.0.0 | `web` | Native app-menu XML/SCSS assets only. |
| `baseer_legion_compat` 19.0.1.0.0 | `legion_enterprise_theme` | Navbar SCSS assets only. |
| `legion_enterprise_theme` 19.0.1.0.1 | `web` | Vendor backend SCSS only; no data or hooks; auto-install false. |

None of the selected manifests declares a pre/post-install hook, uninstall hook, post-load hook or demo data. Their loaded XML contains metadata, views, report templates, rules/ACLs and the batch sequence, not QA business fixtures. No selected XML assigns `res.users` groups or rewrites tax/company master values. ACLs reference existing accounting/POS groups; they do not grant users new membership. The explicitly loaded native POS menu is renamed **Direct sales**, and its dashboard action gains the accepted summary/current-company domain. These are intended shared UI metadata changes, not business-record changes.

The release baseline says native `point_of_sale` 1.0.2 is already installed on main; therefore its original data setup should not be reinstalled/upgraded merely because it is a dependency. Likewise retain existing `baseer_core` 19.0.1.0.0, EH accounting base 1.8.0, dynamic reports 1.8.1 and cash categories 19.0.1.3.1. No selected dependency introduces payroll. Rehearsal must verify the actual module install plan contains only the agreed candidates and necessary already-known dependencies.

## Migration compatibility

- `baseer_purchase_batch/migrations/19.0.1.2.0/post-migration.py`: only on an upgrade with a prior version, initializes existing line `is_credit` from missing payment method. It does not create, repost or change native bills/payments. It is not a fresh-install seed and exits without a prior version.
- `baseer_pos_summary/migrations/19.0.1.1.0/post-migrate.py`: on crossing that upgrade boundary, initializes `day_schedule` from existing `period_scope`. It changes operational metadata only, not amounts/customer counts/native postings. Odoo's migration runner invokes versioned migrations for upgrades, not a normal new install.
- `baseer.pos.day.archive.init()` recreates **only its own SQL view** over summary/closure/company tables. It does not insert/update source rows. Native ORM creates the new stored tables/columns before model initialization; fresh source tables are empty. Negative closure view IDs and the 366-day bounded series create no persistent business records.
- Existing POS records receive new fields/default false/null and nullable unique links. The dedicated-config partial unique index applies only where `baseer_summary_only` is true, so ordinary pre-existing configs do not collide. Fresh new tables contain no source records requiring a data migration.

Main is described as three companies with zero moves. That avoids a historical conversion need; it does not replace the required clone installation and post-install source/count checks. There should remain zero batch/summary/closure/entry business records after installation, without opening/saving entry forms.

## Production setup is separate from promotion

There is **no automatic summary POS or service-product creation** in the Baseer addon. `summary._default_config()` searches for the active company's existing dedicated config; `day_entry.default_get()` creates only unsaved one2many commands from its existing methods. Merely opening the summary entry does not create config/product/tax/account data. The dashboard summary card needs an existing dedicated config; the direct entry menu is intentionally inactive. Therefore a fresh installation alone cannot make the summary card operational.

To enter positive sales, each production company needs explicit approved setup:

1. One active dedicated summary POS, SAR currency, active sales/invoice journals, no rounding/fiscal-position/preset transformations.
2. An active service product and valid company income account; a simple active sales percentage tax with full tax repartition/accounts. Native gross-price inversion supports existing inclusive/exclusive tax configuration without rewriting the tax.
3. One to 25 active manual payment methods with active company payment categories and compatible journals/accounts. At most one cash method. Cash requires liquidity; bank requires actual liquidity as outstanding account; each application requires its own reconcilable current-asset clearing account. Native intermediary receivable must be active/reconcilable and company-correct.
4. Existing POS plus accounting manager privileges for configuration, as already enforced by the accepted addon. No role changes are part of promotion.

Native `pos.config.create` and native setup helpers can themselves create sequences or missing journals/payment methods. Do not invoke a setup helper or copy QA configuration as an incidental installation step: any such production setup must have its own explicit values and before/after evidence. In particular, do not reuse QA product/category/account IDs or infer bank/platform account mappings from labels. DAY OFF entry is allowed without POS configuration through its dedicated backend path, but this does not create a summary config.

Purchase batches likewise need production category-to-service-product mappings, valid expense accounts, suppliers and chosen native manual outbound payment methods. The VAT toggle reads the company's existing principal 15% purchase tax; it does not create/fix tax setup. Credit remains explicit. Missing configuration should yield the existing validation/setup requirement, not synthetic fallback data. Ordinary native bills and suppliers are not migrated into batches.

## Report and native-code boundary

The layout addon itself is presentation-only: report codes `profit_and_loss`, `cash_flow`, `baseer_cash_categories`; Arabic PDF font selection is language-conditional. Category display and theme/navigation changes are also intended UI changes. No candidate imports or overwrites Baseer core or vendor report files; byte-for-byte preservation is for the lead's source-manifest comparison to establish.

**Important qualification:** installing `baseer_pos_summary` changes report behavior through the declared `models/cash_report.py` inheritance of `eh.account.dynamic.report.handler.baseer_cash_categories`. It traces reconciled collections to approved dedicated one-order summary sessions, validates company/order/ledger evidence, allocates proven tax and marks source links. Ordinary/no-summary paths delegate to the existing handler. It does not write ledger entries or redefine ordinary profit-and-loss accounting. Application clearing is not treated as actual cash before settlement. Thus release wording should say “existing report engine retained, with the accepted POS-summary evidence extension,” not “only report styling changes.”

Native POS create/write/close hooks are guarded by owned summary links/internal authorization and delegate normal POS paths to super. Native cashier functionality is not replaced. Company mutex `UPDATE res_company SET id=id` occurs in explicit financial/configuration actions, not at installation and does not alter company values. No automatic external message was found: WhatsApp actions return a prepared URL for the employee to send manually.

## Required rehearsal evidence

- Exact candidate source retained; no payroll module installed; no unintended native module upgrade.
- Three original company identities, users/group memberships, taxes, accounts, journals, products, payment methods and existing POS configs preserved; any schema defaults are additive and separately identified.
- Zero new `account.move`, `account.move.line`, invoices, payments, POS orders/sessions, batches/summaries/closures from installation. New business tables and archive view query successfully with empty results.
- Original report routes/Arabic PDFs and native cashier routes load; shared menu/domain changes and desktop/mobile theme render correctly.
- Fresh summary/purchase forms may report missing production configuration. Record that separately from code availability and do not claim the module is ready for financial entry until semantic setup is completed.

No additional application patch is requested by this audit. Production cutover remains conditional on the clone rehearsal, immutable candidate, fresh recovery backup and independent final review described in `MAIN-PROMOTION.md`.
