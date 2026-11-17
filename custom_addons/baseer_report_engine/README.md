# Baseer Report Engine

Odoo 19 Community addon. It stores financial report definitions as data and computes them from `account.move.line` for the companies active in the session.

Install `baseer_report_engine`. Open **Invoicing → Accounting → New Version → Balance Sheet (New)**. The module includes Balance Sheet and Profit and Loss (New). Profit and Loss covers the selected period, including six income and expense account types. Trial Balance is available as an account grid, and General Ledger provides cumulative account balances and paged journal items.

The engine depends only on `account`, `analytic` and `web`. It does not depend on Odoo Enterprise accounting reports, OCA, or ERP Heritage.

Amounts follow the user's record rules. A balance sheet date is cumulative through that date. Earnings are split on the active company's fiscal year. Liability, equity and earnings lines reverse the natural credit sign so those balances read as positive. Previous years also include `equity_unaffected` posted before the fiscal year, so an allocation made in an earlier year still keeps the statement in balance.

The grid aggregates journal items by account and company for each date scope. Analytic selections use the same per-line weighting as statements. Initial P&L balances are reset at each company fiscal year, with prior earnings carried to its unaffected earnings account.

Grid definitions declare grouping fields in `grid_groupby` and column tokens in `grid_columns`; `_grid_balances` accepts a tuple of grouping fields, and `_grid_layout` expands the column tokens. Future grids can supply their own row and drill policies. When no unaffected earnings account exists, prior P&L is carried to a synthetic undistributed profits/losses row.

Grid drill-down lists raw journal items, like statements: analytic weighting and currency conversion affect displayed amounts, not the raw journal item values.

The General Ledger uses the shared grid aggregation and fiscal carry-forward helpers, grouping by account and company. The Partner Ledger backend groups receivable and payable activity by partner across active companies, without a fiscal-year reset; its selected account types, partner and category filters also apply to opening balances and drills. Both return a Total row on the last page. Partner Ledger XLSX and PDF exports reuse the ledger detail calculation, expand the selected partners without paging, and include the active partner and account filters.

General Ledger unfolding ranks journal items per account and company after applying access rules. Partner item pages rank the selected partner’s lines after access rules and calculate the carried balance from earlier items. The client reuses the ledger paging, drill and breadcrumb state, with partner and category selectors and partner-specific columns.

## Design notes

Cash Flow excludes accounts specified by code or ID in the comma/space separated
system parameter `baseer_report_engine.cash_flow_excluded_accounts`. Company 2
(Al Moallem Al Shami) should set this to 105002 (transit, default account of the
cash journal «وسيط نقل السلف التاريخية») without changing the account.

The report toolbar uses the instance theme's primary button colour, keeping it consistent with the rest of the app.

Partner-less receivable and payable items are allocated to the partners on their reconciliation counterparts by the partial reconciliation amounts. Any remaining amount stays with Unknown Partner. Journal Items drills show the full journal item amount, including when the ledger displays only an attributed share.
