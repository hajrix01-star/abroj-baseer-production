# Dashboard 2: guarded profit and loss details

Status: design only; not implemented or approved for production. The dashboard’s current `get_drilldown` returns a raw `account.move.line` list and cannot represent a tax amount allocated across source lines. `baseer.report.drill` and `ReportDrillDialog` also require the active company, but Dashboard 2 permits another authorized company or all its configured companies. Reusing that entry point unchanged would either fail legitimate scopes or expose a mismatched detail.

## Contract

Keep the existing `AmountDetailsDialog` as presentation and introduce a small Dashboard 2 controller and guarded service entry points `get_pnl_details(descriptor, selector, page)` and `open_pnl_detail_source(descriptor, selector)`. The descriptor contains only existing dashboard company/period/view/range, a known row key, selected column or total and an exact boolean `tax_inclusive`. Reject unexpected keys, invalid types, unknown rows/columns/children, unreasonable serialized inputs and periods, and invalid pages. A client may not provide SQL domains, arbitrary model names, line IDs as authority, or company lists.

## Authorization and period

On each call run `_check_reader`, re-resolve `company_key` with `_scope`, verify every company against the user’s allowed companies, and derive the exact selected period with `_period`/`_pnl_bounds` and server-side column clipping. Set `allowed_company_ids=[company_id]` and `with_company(company)` separately for each company only after validating membership; never use `sudo`. Apply posted-only, date and company filters consistently with the displayed report. Reject mixed company currencies unless a separately approved conversion contract exists. Preserve existing bounds on period and detail size, and fail explicitly if a complete result cannot be proved.

## Contributions and source lineage

1. Recompute the selected Dashboard 2 row and category/account membership for each company and period with the same verified, Decimal-based accounting source used by the displayed tax basis. Preserve the existing dashboard classification and show its signed account contributions; do not assume its operating categories equal the differently classified Baseer result.
2. For an account child, construct the existing Baseer profit-and-loss filters with the validated company, exact dates, all journals, and selected tax basis; call the profit-and-loss provider under that company’s validated environment with an account selector. Reuse its `_drill_rows`/`_get_drilldown` accounting and source validation so allocation and Noorix evidence follow the same rules. Preserve natural account sign versus dashboard row sign explicitly. Verify the sum of returned source contributions agrees with the displayed account amount at company-currency precision before returning a detail; reject ambiguity and do not fabricate a tax-line amount.
3. For an aggregate row, first present validated account contributions per company, with signed amounts; then open the selected account contribution. Sum only same-currency values with Decimal and round according to the shared company-currency contract. No cross-company or cross-request financial cache.
4. An opaque, strictly shaped source selector must carry its validated parent descriptor, company/account and source-line selector. On open, recompute or revalidate parent membership, date, category, company and read access, then delegate to the Baseer profit-and-loss source-opening path. Reject forged IDs and stale or removed membership. Do not expose inaccessible records or silently exclude a company.
5. Channel children are currently not drillable; retain that behavior until a separately verified channel-provenance contract exists. Dashboard proportional channel splits must not be represented as proven payment contributions.

## UI and export

The frontend forwards the exact selected tax basis and period, displays backend-formatted contribution values, and closes or invalidates details when scope changes. Arabic and English, RTL/LTR, mobile and desktop, loading, error and access-denied states are required. CSV headings and rows, comparison periods and drill source selection must use the same basis; the client performs no financial allocation.

## Required verification

Test actual tax and no-tax invoices, shared and mixed taxes, refunds, rounding, Noorix summaries, POS and unallocated channels; revenue/expense accounts and formula categories; multiple companies including company not active, all-company scope and mixed-currency rejection; blocked records, forged selectors and stale membership; date clipping, previous periods and columns; source drill-through; screen/CSV/detail reconciliation to the halala in both modes. Test on the isolated QA data with known rollback, measure latency and memory, and retain production as NO-GO until independent financial and access review.

## Feasibility

Odoo model extension, existing `AmountDetailsDialog`, verified profit-and-loss contribution methods and request-local caching are already present, so no new dependency or schema is necessary. This is not a drop-in reuse of `ReportDrillDialog`: its active-company guard must not be weakened and Dashboard 2 needs its own controller, endpoints and cross-company aggregation. Current `_accounting_gross` and `_inclusive_drill_domain` do not establish equivalence with the Baseer tax proof and must not be substituted for it. The source-comparison and sign rules need executable fixtures before implementation can be accepted.
