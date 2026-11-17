# Saudi VAT report (work in progress)

This module uses the installed Saudi return's tag and aggregation expressions. The existing Baseer VAT report uses the same formula sign and sums the balances of lines with each tag. It does not add untagged tobacco service fees to the return; its untagged-other-tax exception also excludes account 201021. This module likewise does not deliberately add tobacco fees to return boxes. If a fee is configured with a Saudi VAT tag, both reports include that tagged balance.

This implementation is incomplete and must not be used for filing. In particular the tax grouping view, complete reconciliation diagnostics, company periodicity default, tag-negation handling and the requested fixture coverage are outstanding. Reconciliation is an experimental comparison and can differ for reasons that are not yet diagnosed. The original VAT report remains unchanged.
