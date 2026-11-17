# Baseer Report Engine

Odoo 19 Community addon. It stores financial report definitions as data and computes them from `account.move.line` for the companies active in the session.

Install `baseer_report_engine`. Open **Invoicing → Accounting → New Version → Balance Sheet (New)**. The module includes Balance Sheet and Profit and Loss (New). Profit and Loss covers the selected period, including six income and expense account types. Trial Balance is available as an account grid, and General Ledger provides cumulative account balances and paged journal items.

The engine depends only on `account`, `analytic` and `web`. It does not depend on Odoo Enterprise accounting reports, OCA, or ERP Heritage.

Amounts follow the user's record rules. A balance sheet date is cumulative through that date. Earnings are split on the active company's fiscal year. Liability, equity and earnings lines reverse the natural credit sign so those balances read as positive. Previous years also include `equity_unaffected` posted before the fiscal year, so an allocation made in an earlier year still keeps the statement in balance.

The grid aggregates journal items by account and company for each date scope. Analytic selections use the same per-line weighting as statements. Initial P&L balances are reset at each company fiscal year, with prior earnings carried to its unaffected earnings account.

Grid definitions declare grouping fields in `grid_groupby` and column tokens in `grid_columns`; `_grid_balances` accepts a tuple of grouping fields, and `_grid_layout` expands the column tokens. Future grids can supply their own row and drill policies. When no unaffected earnings account exists, prior P&L is carried to a synthetic undistributed profits/losses row.

Grid drill-down lists raw journal items, like statements: analytic weighting and currency conversion affect displayed amounts, not the raw journal item values.

The ledger uses the shared grid aggregation and fiscal carry-forward helpers. Its ledger report kind and `grid_groupby` definition provide an extension point for future grouping layouts such as a partner ledger; the current ledger implementation supports account and company grouping. The account Total row is returned on the last page.

Ledger unfolding ranks journal items per account and company after applying access rules; only the requested page is loaded. Exports include all items for unfolded accounts. A future partner ledger can reuse the grid aggregation and ledger page presentation with a partner-specific grouping, opening balance and drill policy.

## Design notes

The report toolbar uses the instance theme's primary button colour, keeping it consistent with the rest of the app.
