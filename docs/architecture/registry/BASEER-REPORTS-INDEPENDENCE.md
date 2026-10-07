# BASEER-REPORTS-INDEPENDENCE-20261007

Status: approved direction for new Baseer reports; old-report retirement is not approved by this decision.
Classification: architectural dependency boundary. Base: `9393b31ebd9410a80dbd119c72d7e3ff4246d636`.

## Decision

- Every new Baseer report, financial or operational, owns its computation, access controls, UI and exports in Baseer source. It may use supported Odoo Community models/services relevant to its domain, but must not depend on, import, inherit a template from, or call `eh_account_base` or `eh_account_dynamic_reports` (ERP Heritage).
- The Baseer reports navigation owner remains `baseer_reports_menu`, with only `account` as a dependency. The current Saudi VAT, POS tobacco and design-preview addons already depend on this owner without depending on ERP Heritage.
- Real P&L, General Ledger and cash-in/out reports are not created by moving menus or by the synthetic preview. Each needs an explicit source-of-truth, period, company and permissions contract plus independent reconciliation tests before it is shown as a live report.

## Existing boundary and retirement gate

`baseer_report_layout`, `baseer_arabic_ui` and `baseer_cash_categories` still reference or depend on ERP Heritage. Existing Heritage P&L/GL menus and records are not modified here. Before disabling or uninstalling Heritage, inventory all dependents and saved report data, establish functional and numerical parity for replacements, run isolated uninstall/migration rehearsals with backup/rollback, and accept the result in QA. No production removal is authorized by this ADR.

## Current navigation phase

Move only the existing `baseer_reports_menu.menu_baseer_reports` to a top-level Odoo section, preserving its XML ID, child actions, and groups. The independence rule applies to all newly built reports, while placement of existing operational POS, procurement and payroll reports is a separate scope decision. Reversal restores the root menu's previous `account.menu_finance_reports` parent; it does not migrate report data.

## 2026-10-07 owner amendment — one entry under Invoicing / Reporting

The owner superseded the top-level placement after reviewing QA: the intended journey is **Invoicing → Reporting → Baseer Reports → select a real report inside one report page**. Keep the existing report modules and financial computations independent; moving navigation does not move source code into `account` or ERP Heritage. Preserve the root menu XML ID but restore its parent to `account.menu_finance_reports` and make it the sole visible Baseer report entry. Preserve individual report action XML IDs for existing deep links and rollback, while suppressing their duplicate navigation items. Keep the synthetic design-preview action separate from the real report selector and unavailable in ordinary report navigation. Only installed, permitted, real reports may appear. This is a CONTROLLED multi-module navigation/UX change, not approval to build the remaining financial calculators or retire Heritage.
