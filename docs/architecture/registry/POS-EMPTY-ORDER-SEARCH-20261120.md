# POS-EMPTY-ORDER-SEARCH — local search initialization

Owner: `baseer_pos_customer_identity` 19.0.1.0.15. Baseline: main
`150b6d544`. Classification: LOCAL. Native POS Store -> default search details
-> TicketScreen -> SearchBar -> existing order filtering. This map is unchanged.

Confirmed on production register 27: clearing the automatic `عميل` search reveals
six active orders instead of two; returning to Orders restores that search.
Native `PosStore.getDefaultSearchDetails()` copies the selected partner's name.

The Baseer PosStore extension now clears only the initial search term and keeps
the inherited search field. Explicit customer searches and other screen state
remain native. No data, schema, company scope, calculation, payment, printing or
Odoo core change. Existing frontend assets already include the changed file.

Validation: native method reproduced the failure before applying the actual
extension; seven assertions passed afterwards (no order, no partner, generic and
named partners, repeated openings, inherited fields). Node syntax and Git
whitespace checks passed. Runtime acceptance: open Orders with selected customer,
leave/reopen, then explicitly search/clear. No layout change or load test needed.

Release scope: this addon only, ordinary PR/CI, protected QA, runtime acceptance,
then protected production approval/deploy with paired recovery backup. Rollback:
revert this override/version through the same release process; no data rollback
is required by the frontend change itself.
