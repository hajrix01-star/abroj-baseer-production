# S5 restricted summary-entry role — independent access findings

2026-09-08. Read-only audit by s2_review; no application/group assignment/data changes. Scope is the proposed role only, not approval of deletion or tax-policy changes still being clarified. Existing QA4 architecture reused.

## Recommendation

Create an unassigned role implying **base.group_user only**, with explicit narrow custom-model/master-read permissions. Do **not** imply point_of_sale.group_pos_user or account.group_account_invoice. Use a private, fixed-purpose native posting scope only after caller authorization, creator/current-company/state/input checks. `sudo()` in this scope keeps the original uid for native audit fields, but it bypasses record rules: company/configuration/method/product/tax/journal validation must run explicitly inside the validated operation. Reuse the existing in-process identity token; never accept a JSON boolean, arbitrary model/action name, record IDs or generic values for an elevated executor. Original manager/POS/accounting behavior remains unchanged.

This is cleaner and more enforceable than granting broad native groups then maintaining dozens of negative report/accounting overrides. The role is created for later use and must not be assigned to any existing employee/user by this task.

## Why native groups are too broad

- Installed point_of_sale/security/ir.model.access.csv grants POS users read report.pos.order and broad pos.order/line/payment/session access, stock operations and pos.config write. Existing custom summary ACLs also use that native group.
- Current summary.action_approve requires POS user + account.group_account_invoice. Installed account/security/ir.model.access.csv grants that billing group account.invoice.report read and account.move/account.move.line CRUD, as well as reversal/send wizards. These grants are unnecessary for an employee who should only submit summaries.
- Odoo ACLs are additive; adding a read-only/zero-permission ACL or hiding menus cannot subtract inherited rights. Group-specific ir.rules also union with other group rules. Manager overrides must be explicit: the restricted predicate should not strip an authorized manager's existing access merely because the role is accidentally combined.

## Minimal authorization contract

1. Permit the current-company day-entry and child-slot workflow, with existing creator isolation. Grant only the read master-data ACLs proven necessary by a fresh minimal-role fixture: dedicated pos.config, pos.payment.method/payment category, product/service and tax/repartition metadata; currency/company permissions as already available. Do not add account.move, account.move.line, account.payment, pos.order, pos.session or report ACLs. Account/account-journal master reads should be added only when an actual non-elevated form/native-quote path requires them, with company scope.
2. Company/config master rules must expose only the approved dedicated configuration and configured company payment methods. Existing native cashier open_ui must explicitly reject this role; the new summary-card navigation can allow the role after the same dedicated/current-company checks. Native dashboard statistics may read session data even when its UI body is hidden: verify a minimal-role dashboard journey, and prefer the dedicated entry menu if the native dashboard would require broad session access.
3. Allow role-based approval as an alternative to the original native role pair, then authorize/lock/check ownership and build the fixed native transaction privately. Full native setup checks, exact native VAT, native date locks, source identity, method membership, atomic rollback and idempotence remain mandatory. Preserve caller uid on summary approved_by and native create/write audit. Elevation must not escape to returned actions, ordinary source reads, unrelated methods or subsequent RPC requests.
4. Existing custom summaries/allocations/closures should be limited to the role's permitted own source records, if history is allowed. Creator limitations used for viewing must not hide conflicting other-user summaries/closures from overlap checks: validate overlap under narrowly scoped company-authorized internal reads, without revealing other-user financial values. This is a critical difference between viewing authorization and business invariants.
5. The read-only day archive is SQL aggregated across company/date; ORM source-record rules do **not** automatically apply inside its SQL. A rule saying any source belongs to the user leaks the other shift's amounts/customers. The shortest interpretation of entry-only/no-reports is **no archive/report ACL for this role**, while keeping its just-saved form and explicitly authorized WhatsApp. If own history is required, allow only archive groups whose every source belongs to that user, or use an owner-filtered source list; do not silently expose a mixed-owner daily aggregate.
6. Deny analytical grouping/export routes on custom summary/allocation/archive to the restricted role outside the fixed internal operation. Normal entry computations and readbacks may continue. An employee can inherently observe their own entered values; the enforceable promise is no reporting endpoints or other users' business data, not preventing someone from manually adding numbers they can see.

## Concrete reporting/data surfaces to test

| Surface | Model / public endpoint | Expected strict-role boundary |
|---|---|---|
| Custom daily means/timeline | baseer.pos.daily.report action_generate/action_timeline; baseer.pos.daily.report.line read/search_read/web_read_group | No ACL; reject direct RPC, not only hidden menu. |
| Custom monthly/shift analysis | baseer.pos.summary and baseer.pos.summary.allocation read_group/web_read_group/_read_group-backed analytics | Deny report grouping; ordinary authorized saved-entry data remains separately scoped. |
| Unified daily archive | baseer.pos.day.archive search_read/read_group/action_open | Prefer no role ACL due mixed-owner SQL aggregate issue. |
| Native POS analysis | report.pos.order search_read/web_read_group/read_group | No native POS group/ACL. |
| Native POS sale-details | report.point_of_sale.report_saledetails.get_sale_details; pos.details.wizard.generate_report; pos.daily.sales.reports.wizard.generate_report; sale_details_report PDF route | Detail method's native pos.order.search must fail without native order read. Wizard ACLs are manager-native and not granted. Test direct report route too. |
| Native invoice analysis | account.invoice.report search_read/read_group; account.move/line reads/export_data | No accounting/billing group or ACL. |
| EH reports, including cash categories | eh.account.dynamic.report get_by_code/get_default_options/render/render_xlsx/export_xlsx_attachment/render_pdf/export_pdf_attachment/expand_line/get_drilldown_for_line/get_analytic_column_drilldown_page | No EH group; original _eh_check_access checks enforce report ACL. Test JSON/XLSX/PDF/direct URLs rather than adding broad vendor patches. |
| EH saved/cached data | eh.account.report.execution, eh.account.report.wizard, eh.account.report.saved_view, fold.state, annotation, linked attachments | No EH ACL; test stored payload/attachment read cannot bypass rejected report render. |
| Native source buttons | summary.action_view_order/action_view_session/action_view_moves, day-entry source drill | Hidden for restricted role and native target ACL denies direct source access; guard action methods where useful to provide clear error. |
| Cashier operations/configuration | pos.config.open_ui/open_existing_session_cb; original pos.order/session/payment create/write and session closing RPC | Denied for restricted role outside the fixed private summary posting operation. No extra native ACL to make navigation work. |

## Verified native private-handler behavior

Installed odoo/service/model.py get_public_method lines45–71 walks the full class MRO and rejects an inherited @api.private method even if a concrete override omits the decorator. EH report_handler_base.compute and other internal computation methods carry that decorator. Therefore concrete profit-and-loss/cash-category compute overrides are not a new public RPC bypass merely because the override lacks an explicit decorator. Existing cash handler's private source computation continues using company checks and ORM reads. Do not modify every vendor handler based on that false concern.

## Required evidence before role GO

Fresh temporary user with only base user plus new role; assert actual effective groups lack native POS, invoice and EH groups. Positive one/two-shift native posting, zero/DAY OFF and WhatsApp; caller audit preserved; late second-step failure all-or-none. Direct forbidden RPC/search/group/export/report routes rejected, hostile context cannot inject elevation, foreign/current-company and other-creator data denied. Another operator's saved shift/closure still blocks conflicting entry. Manager role retains existing reports and source drill. Verify the new role remains unassigned on persisted real users after test rollback/cleanup. Creating this role and its narrow elevated posting path needs G0/G2 review before code, even though UI is small.
