# BWork leadership bridge (optional)

Local implementation of C1 in `docs/build-governance/BWORK-CENTRAL-SALES-20261019.md`.
It adds no report tables, goals, source ACL grants or business-write endpoints.

Prerequisites: Odoo 19, `baseer_bwork`, `baseer_sales_heat_calendar` **including the
canonical unified-sales day adapter and exact day Amount fields in this change**,
and `baseer_purchase_expense_dashboard`. Install/update these together in an
isolated database before enabling `res.users.bwork_dashboard_view` for a user.
The default is false; administrators control it. Effective permissions and
bootstrap expose the optional `dashboard_view`/`leadership_version=2` fields.
Ordinary published-dashboard, group, company, source-model and target read access
is still required, and financial reads never use sudo. Only the user's protected
switch read follows BWork's existing narrowly scoped sudo pattern. No new model
ACL is necessary: the module only extends existing users and the abstract service.

The two GET routes require a real internal user session and reject request bodies,
unknown/repeated query fields and token fallbacks. Report queries require month
`1900-01` through `9998-12` and period `today|yesterday|month|date`; custom date is
required only for `date` and must belong to that month. Today/yesterday select the
Riyadh day independently of the chart month. No company means all authorized
companies, at most ten. Options retains every authorized company, including when
there are more than ten, so a single-company report can still be selected.

One combined 100,000-row request preflight counts distinct records per source
model/company across merged disjoint intervals (not the gap between historical
and current months). It includes all-state summaries and allocation rows,
closures, conservative POS/posted Sales invoice candidates, native public-RPC
comparison intervals, every selected/previous/current heat month plus its 8-week
history, and supplier bills/credits. The canonical ancestry, split-payment,
source and 1,000-contributing-heat-session limits remain additional fail-closed
guards. A source/company failure fails the entire request. Responses are bounded
at 1 MiB and have `Cache-Control: no-store`.

Headline sales call `get_baseer_sales_metrics` for exact native date bounds.
Daily series and targets call `get_baseer_heat_calendar`, in the same request
transaction and clean single-company Riyadh context. Selected/current/prior
headline totals are explicitly reconciled against the corresponding central heat
daily money, including current/future records; any mismatch fails the report.
Spending version2 combines posted gross supplier bills less credits by invoice
date, including foreign source documents at their native posted SAR company
amount, with non-bill operating expense balances by accounting date. Its required
`spending_breakdown` contains purchases and operating Amounts; their sum equals
the existing spending Amount. Payroll contributes expense lines, not net pay,
payments, advances or source-screen totals. Depreciation and proven stock COGS
are excluded under the purchases-at-recording basis; unsupported direct-cost,
asset-cost adjustments and bill-target entry reversals fail closed. All supplier
bill moves are globally outside operating, regardless of date/currency. The
difference is not profit or cash flow. Monetary aggregates and ratios use Decimal/HALF_UP and
English-digit two-decimal strings. No arbitrary source actions/IDs are returned.

All-company explicit target requires a target in every requested company,
including companies with no sales. Mixed company baseline/target evaluation is
neutral. Missing/incomplete companies remain explicit. Positive complete past
days form weekday averages. Daily means include recorded zero sales but exclude
missing/incomplete days. Current-month bounds always run from month start through
yesterday, independently of the selected chart month; the first day has no
completed sample. Previous comparison is the same dates of the previous month,
with changes unavailable if that month is shorter or either series has gaps.
Forecast is explicitly estimated as complete-day mean × current calendar days,
requires at least seven complete observations, and is unavailable with any gap.

## Isolated verification

The original local C1 handoff did not have an available Odoo/PostgreSQL runtime;
its compilation and pure checks were not ORM/HTTP acceptance. Current BCS runtime
execution and results belong to `docs/build-governance/BWORK-COMBINED-SPENDING-20261020.md`
and `output/bwork-spending-discovery-20261020/`, and remain pending until their
actual isolated run completes. Source or pure checks are not financial QA/Live
parity evidence. `python tests/run_contract_checks.py`
runs the three pure contracts tests without Odoo. `python tests/wire_fixture.py`
prints a synthetic JSON fixture through the real producer methods for mobile
decoder interoperability; its source seams intentionally do not exercise source
ACLs, budgets or financial parity. To run actual fixtures in a disposable
database with the repository's approved Odoo runtime/addons paths:

```sh
odoo -d bwork_leadership_isolated --test-enable --stop-after-init --without-demo=all \
  -i baseer_bwork_dashboard --test-tags /baseer_bwork_dashboard
```

For an already prepared disposable database, use `-u baseer_sales_heat_calendar,baseer_bwork_dashboard`.
The registered TransactionCase/accounting tests create actual posted Sales and
supplier invoices/credits and central goals, verify native sales parity, denied
ACLs/published/group/company access, no goal writes, current-month independence,
all-company target completeness and combined draft-summary budget. HttpCase tests
exercise sessions, options/no-store, strict requests and unauthenticated access.
These fixtures may write **only inside the isolated test transaction/database**.
QA/live financial parity and AR/EN native rendering remain separate acceptance.

## Combined-spending source guard

The existing request budget is shared with the new bounded financial/provenance
reads across all companies and merged periods. Fixed-table COUNT-only coverage
queries on at most1000 already-authorized move IDs check bill AML completeness
and the proven stock_account19 `stock_move.account_move_id` relation. Their
subqueries stop at remaining-budget+1. They return no hidden IDs or amounts;
native nonzero coverage must equal the caller-secured count before any field
materialization. Zero stock provenance requires no unused stock role. Every
financial/provenance read is limited to1000 rows, uses ordinary access and field
checks, and only contributing operating lines traverse optional HR expense links.
No sudo, ACL grant, monetary SQL, persisted report table or financial write is
introduced. Leadership2 invalidates old client/snapshot semantics through the
existing strict version decoder, without cache/control/outbox wipe.

Entry-reversal ancestors receive the same bounded, ordinary-access stock
coverage check. An unsupported valuation ancestor fails generically instead of
counting a negative operating leg whose original cost was excluded. Ordinary
non-stock operating reversals remain signed operating balances. No special
direct-cost or mixed-asset payroll exception is admitted in this release: those
unproven cases fail closed; ordinary expense-side salary balances remain included.

`TestCombinedSpendingOrm` in tests/test_spending.py adds native posted-document,
company-currency, partition/refund/tax/period, source-link/rule and budget cases.
Its isolated runtime profile additionally installs hr_expense and stock_account;
plain accounting-only and separately stock-authorized users are distinct. Test
execution and financial/ordinary-role acceptance are recorded in the BCS release
evidence, not inferred from this source description or the synthetic wire fixture.
