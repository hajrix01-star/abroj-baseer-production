# Cashier procurement navigation correction — 2026-09-14

## G0 — scope and acceptance

The reported live behavior is a visibility defect: the cashier role inherits the guarded procurement-cashier capability, but the custom menu filter admits only the POS tree.  As a result, a cashier cannot reach the existing **Procurement Requests** menu under Inventory, its request list, or the existing guarded receipt action.

This correction is limited to the cashier navigation and its existing receipt entry point:

- The cashier sees **Inventory → Procurement Requests → New request / Requests**.
- From a sent or manager-received request, the cashier sees the existing actual-purchase receipt action.
- The server-side company checks, request state machine, price-history recording, and inventory receipt behavior are unchanged.
- Cashiers still do not see or gain manager receipt, purchasing custody, custody settlement, supplier bills, accounting, or raw-material-catalogue administration.

Out of scope: changes to request accounting, stock, source products, data, manager controls, or the existing cashier receipt server methods.

## G1 — capacity and continuity

This is a bounded menu/view correction.  It adds no query, table, field, background task, dependency, migration, or data write.  The existing request list pagination and guarded receipt workflow remain the capacity boundary.

## G2 — ERP and authorization contract

`baseer.procurement.request` remains the source of truth.  The cashier may only act through existing server methods, which require the procurement-cashier group, the active company, and a `sent` or `received` state.  Menu visibility is never authorization; the existing server guards and record rules remain authoritative.

## G3 — direct path decision

Reuse the existing Inventory parent, procurement request menus, action, and guarded receipt method.  Do not build a second purchasing application or duplicate receipt screen.  No library or dependency is added.

## Gate register

| Gate | State | Evidence required |
|---|---|---|
| G0 | GO | scope and non-manager boundary above |
| G1 | GO | no data/schema/background change |
| G2 | GO | role/menu and guarded-receipt tests |
| G3 | GO | existing Odoo menus/actions only |
| G4–G5 | pending | Arabic/English menu and sent/received receipt entry checks |
| G6–G8 | blocked | focused suite, independent review, isolated rehearsal and release decision |

## Live operations log

| ID/time | Gate | Type | Intent / result | Impact / rollback |
|---|---|---|---|---|
| CPR-NAV-001 — 2026-09-14 | G0–G3 | Read / decision | Verified the reported defect against the release source: `group_cashier` inherits the guarded cashier capability; `ir_ui_menu._visible_menu_ids` admits only the POS tree, hiding the existing procurement menu tree. The existing form additionally hides the cashier receipt action for `sent` requests despite the server allowing `sent` and `received`. | No application or data write. Rollback is not applicable. |
| CPR-NAV-002 — 2026-09-14 | G4–G5 | Implementation | Added only the Inventory parent plus the existing procurement subtree to the cashier menu allow-list; extended the existing cashier receipt button to its already server-authorized `sent` state; named it “Cashier purchase receipt” / “استلام المشتريات”; added an exact menu-boundary test. | Candidate source only. Rollback is the source commit preceding this change; no data path changed. |
| CPR-NAV-003 — 2026-09-14 | G5 | Test correction | The isolated test proved the native Inventory container is absent from the base visible set because the cashier intentionally lacks the stock-user group. The role filter now admits that container alone without granting stock permissions; procurement children remain constrained by their own groups and the server authorization boundary. | Candidate source only; no live deployment is authorized while the owner supplies additional changes. |
| CPR-NAV-004 — 2026-09-14 | G5 | Isolated verification | A fresh Odoo 19 database installed `baseer_procurement_requests` and `baseer_access_roles` from the candidate and ran `CashierProcurementRoleCase` with exit code `0`. It covered the new Inventory/procurement menu boundary and existing active-company receipt guard. The three temporary test databases and container were removed after verification. | No production, live, QA, source sales, stock, accounting, payroll, or user data changed. G6–G8 remain blocked pending the owner's combined-change scope and independent release review. |
