# Saudi VAT report (work in progress)

This module evaluates the installed Saudi return's tag and aggregation expressions. Odoo 19 tags do not have `tax_negate`: the leading minus in a localization formula determines the sign of the sum of tagged balances. The existing Baseer VAT report uses the same rule. The Saudi chart fixture tests invoices, refunds, zero-rated and exempt sales, reverse charge, drafts and a POS-like journal entry against all 16 boxes and, when installed, the legacy wizard.

The default is the last full month when the company exposes a monthly tax periodicity, otherwise the last full quarter. The Odoo 19 Community accounting module in this workspace does not expose that periodicity field.

The tobacco service fee is not deliberately added to return boxes. The existing report excludes untagged tobacco fees from its other-tax exception using account 201021. If a fee is configured with a Saudi VAT tag, both reports include that tagged balance.

This implementation is incomplete and must not be used for filing. The tax grouping view, complete reconciliation diagnostics and reconciliation tobacco-account exclusions are outstanding. Reconciliation is an experimental comparison and can differ for reasons that are not yet diagnosed. The original VAT report remains unchanged.
