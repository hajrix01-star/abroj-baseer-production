# Saudi VAT report

This module evaluates the installed Saudi return's tag and aggregation expressions. Odoo 19 tags do not have `tax_negate`: the leading minus in a localization formula determines the sign of the sum of tagged balances. The existing Baseer VAT report uses the same rule. The Saudi chart fixture tests invoices, refunds, zero-rated and exempt sales, reverse charge, drafts and POS-like entries against all 16 boxes and, when installed, the legacy wizard.

The default is the last full month when the company exposes a monthly tax periodicity, otherwise the last full quarter. The Odoo 19 Community accounting module in this workspace does not expose that periodicity field.

The grid, tax grouping and drills follow tax tags without filtering by account, matching the existing report. In particular, a tobacco service fee with `include_base_amount` can carry a VAT base tag and must be included in the tagged base. Tobacco fee accounts (including account 201021, configured accounts, and accounts on taxes named or grouped as a tobacco service fee) are excluded only from the VAT accounts used for reconciliation movement.

Grouping assigns each tagged balance once and places items that cannot be attributed uniquely to a tax in an unassigned row. Reconciliation includes cash-basis transition accounts in movement and shows their period balance as a pending cause, alongside untagged VAT-account entries and excluded drafts. The original VAT report remains unchanged.
