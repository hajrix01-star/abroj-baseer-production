# Saudi VAT report (work in progress)

This module evaluates the installed Saudi return's tag and aggregation expressions. Odoo 19 tags do not have `tax_negate`: the leading minus in a localization formula determines the sign of the sum of tagged balances. The existing Baseer VAT report uses the same rule. The Saudi chart fixture tests invoices, refunds, zero-rated and exempt sales, reverse charge, drafts and a POS-like journal entry against all 16 boxes and, when installed, the legacy wizard.

The default is the last full month when the company exposes a monthly tax periodicity, otherwise the last full quarter. The Odoo 19 Community accounting module in this workspace does not expose that periodicity field.

Tobacco fee accounts are excluded from the VAT figures and reconciliation, including account 201021, configured accounts, and accounts on taxes named or grouped as a tobacco service fee. The existing report excludes untagged tobacco fees from its other-tax exception using account 201021; unlike this report, it can include a fee carrying a Saudi VAT tag.

This implementation is incomplete and must not be used for filing. Grouping assigns each tagged balance once and places items that cannot be attributed uniquely to a tax in an unassigned row. Reconciliation shows untagged VAT-account entries, excluded drafts and non-exigible VAT-account entries; cash-basis transition accounts and other differences require further validation. The original VAT report remains unchanged.
