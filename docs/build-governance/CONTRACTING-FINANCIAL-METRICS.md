# Contracting financial metrics — 2026-11-03

Baseline: `9d0d6c00`, branch `codex/contracting-financial-metrics-20261103`.
Scope: `abroj_project_dashboard`, `abroj_contracting`; financial read indicators,
their existing views/API, and customer remaining balance. No journal rewrites,
source-data normalization, budget approval, new dependency or permission expansion.
Architecture: issued vouchers -> native posted payments/analytic lines;
posted expense analytic lines + existing standalone negative analytics + explicit
manual actual -> project/category actual. Contract commitments -> commitment margin.
Explicit project budget, else estimated cost -> forecast/over-budget comparison.
Detailed budget sum remains informational; potentially overlapping lines are not
silently approved. Financial calculations stay on the server using decimal sums.

## Contract and gates

Receipt, cash/bank, receivable and payable lines cannot be actual expense.
Posted expense analytics include both signs so refunds/reversals reduce cost.
Retain existing negative standalone analytics and manual actual; manual amounts
are explicitly additional costs, with no automatic deduplication claim.
Use the same scope/filter for project and budget categories, restricted by company
and project analytic account and existing record access. Preserve cash totals.
Customer remaining excludes receipts linked to subcontractor refunds.
Missing approved budget means unknown forecast and no claimed budget compliance;
the API carries availability flags/null and views show a missing-budget message.
Contract margin remains contract minus registered commitments, labeled accordingly.

| Gate | Decision | Independent evidence |
| --- | --- | --- |
| G0 | approved | `erp_review`: read-indicator repair, no financial source edits |
| G1 | approved | same deployment/data volume, no new write or concurrency path; existing project owner use; no broad load test justified |
| G2 | approved | `erp_review`: expense/net filter, standalone compatibility, explicit budget precedence, refund/customer separation |
| G3 | approved | `erp_review`: existing Odoo 19/account APIs, no libraries/schema migration |
| G4 | in review | existing native form and AR/EN web cards; add accurate labels/availability only |
| G5–G8 | pending | focused ORM regression suite, CI, independent candidate review and protected release route |

## Operations (append-only)

1. Read existing module owners/tests, source workflow and prior live read-only
   findings; local dirty root left intact. Confirmed incorrect 9,700 consists of
   5,000 receipt and 4,700 payable settlement; no posted expense in that sample.
   No evidence of a prior correct implementation; classify as existing logic defect.
2. Fetched official/main and created isolated worktree/branch. Independent ERP
   reviewer approved G0–G3 with the conditions above before application edits.
3. Verification plan: existing isolated Odoo CI (financial regression tests),
   static syntax/XML/JS checks, scoped review. Existing local Docker is available;
   avoid cloning live data or running load tests without a specific uncovered risk.
   Acceptance: receipt/payment excluded; expense debit/credit net; draft excluded;
   standalone/manual retained; company scope; project/category consistency;
   budget precedence/missing/mismatch; refund does not reduce customer receivable.
   Rollback is prior source through protected release; no accounting data rollback
   should be required because no accounting source is edited.
