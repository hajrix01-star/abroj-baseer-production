# Baseer Report Engine

Odoo 19 Community addon. It stores financial report definitions as data and computes them from `account.move.line` for the companies active in the session.

Install `baseer_report_engine`. Open **Invoicing → Accounting → New Version → Balance Sheet (New)**. The first definition is the statement of financial position. Profit and loss, trial balance and general ledger can be added later as further definitions.

The engine depends only on `account`, `analytic` and `web`. It does not depend on Odoo Enterprise accounting reports, OCA, or ERP Heritage.

Amounts follow the user's record rules. A balance sheet date is cumulative through that date. Earnings are split on the active company's fiscal year. Liability, equity and earnings lines reverse the natural credit sign so those balances read as positive. Previous years also include `equity_unaffected` posted before the fiscal year, so an allocation made in an earlier year still keeps the statement in balance.
