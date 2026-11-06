# Contracting accounting issue — 2026-11-03

Baseline62de4aff; isolated branch codex/contracting-accounting-issue-20261103.
Owner abroj_contracting; existing dashboard actual-cost contract19713722 reused.
User authorized the proposed expense accounting step and receipt entry visibility,
with no duplicate journal or actual cost. No retrospective posting of live data.

## G0–G3 contract (independent ERP gate approval)

Confirmed cost -> accountant review wizard -> native posted vendor bill. One
canonical account.move.abroj_cost_id link, SQL uniqueness and cost row lock;
retries open the original bill. Posting is atomic and failures roll back.
Alternative explicit adoption of an existing posted supplier bill validates
company/currency/partner/gross amount/expense lines/project100% and unique link.
Gross source amount is preserved; default no tax, native tax engine only for
selected purchase tax and total validation. User explicitly selects native
supplier, expense account, purchase journal, invoice/accounting dates and taxes.
Recovery via native credit note/reversal; original cannot detach/reset/delete.
No sudo, context bypass, auto partner creation, historical payment edits or
automatic payable reconciliation. Existing payments remain settlements, outside
actual expense. Neither manual_actual nor a second cost source is incremented.

| Gate | State | Independent reviewer/evidence |
| --- | --- | --- |
| G0 | approved | erp_review: authorized accounting action, no automatic old postings |
| G1 | approved | owner project example1 project/5 issued vouchers/14 budget lines; assume2 concurrent accounting clicks, retain native indexes; focused two-request serialization test, no broad load |
| G2 | approved | erp_review: canonical protected link, unique constraint, locks, native bill/tax/analytic source, explicit existing-bill adoption |
| G3 | approved | existing Odoo19 ORM/accounting/TransientModel; no libraries |
| G4 | in review | existing native form/list/dialog and PWA native-record links; AR/EN labels, Western digits, mobile width |
| G5–G8 | pending | permission/idempotency/tax/reversal/actual-cost tests, independent review, protected release |

## Architecture / authority

Cost confirmed amount(gross) -> native bill expense+VAT/payable -> native posted
analytic expenses -> existing actual indicator. Voucher approval -> native
payment cash/receivable/payable -> existing incoming/outgoing and paid indicators.
Adoption links a validated bill; it creates no expense line. Commitment includes
the confirmed source cost once. Refunds net through the existing expense filter.
All numeric validation/rounding and posting decisions are server-owned. Native
monetary storage/API boundaries retained; decimal validation up to2 decimals.

## Operations (append-only)

1. Read existing source, registry, prior metrics acceptance, accounting guards,
   party identity, native Odoo tax API and payment approval flow. Reused current
   financial map; no broad re-audit. New worktree from official/main.
2. Independent ERP reviewer approved G0–G3 with the conditions above before code.
   Direct route: reuse native vendor bill rather than custom journal calculator;
   one link authority avoids inconsistent pointers. Explicit existing-bill option
   handles already-recorded facts without issuing a duplicate bill.
3. Verification planned before creating test state: new protected posting/link
   schema and concurrency are not covered by the previous read-only metric suite;
   reuse the isolated synthetic test PostgreSQL from the prior task. Test one
   owner project and2 simultaneous issue requests; no production load or data
   cloning. Retain raw live documents and existing frozen release procedure.
4. Built native review wizard, protected canonical bill link, inverse source
   view, existing-bill adoption and native posting. Source amounts remain gross;
   supported percentage taxes use Odoo inverse tax details and native total
   validation. Unsupported compound/fixed/mixed-inclusion configurations reject
   explicitly. Native plan column is validated so posted expenses reach actual.
5. First synthetic run found Odoo assertRaises tuple incompatibility and a
   non-project-plan test fixture. Corrected fixtures, then closed source-review
   findings: destination line protection, immutable native supplier match and
   fixed voucher date. Independent reviewer accepted all narrow fixes.
6. Local r3:155 tests passed, zero failures/errors, covering24 new issue tests,
   40 existing contracting cases and91 dashboard/HTTP/module cases. Added25th
   regression for context defaults (cost link, posted move destination, voucher
   accounting partner and confirmed state). It passed in a focused follow-up
   after handling default_move_id before the native line API.
7. Two independent RR cursors through odoo.service.model.retrying returned one
   posted bill and one100 expense/commitment. Initial FOR UPDATE introduced a
   FK KEY SHARE upgrade deadlock (native retry recovered); reviewed change to
   FOR NO KEY UPDATE removed that conflict. Final proof: move111, two requests,
   attempts1/2, one linked bill, actual100, commitment100. Native RR serialization
   retry reloads the winning bill. A script-only metadata typo was corrected
   before the final proof; no application change was required for that typo.
   Artifacts: output/concurrent-issue-final.log, context-guard-final.log and
   verify-concurrent-issue.py. Test data is synthetic and local only.
8. Native form/list/dialog reuse recorded at G4; accountant-only PWA links open
   the issue source or existing native journal. Arabic/English labels and errors
   are present. UI screenshot review and full final-SHA CI remain release gates.
9. Native Odoo dialog verified in isolated preview at EN1280/AR390; no horizontal
   overflow, proper field visibility and voucher/source reuse. Visual review
   exposed a missing Python-code translation marker and native Arabic date
   numerals. Added odoo-python markers and a scoped DateTimeField subclass using
   numberingSystem latn with the native picker/ISO value unchanged. No global
   formatter, tax or business calculation changed. Both dialogs now pass title,
   digits and layout assertions; Arabic calendar digits and editing04/11/2026
   also pass. Test selector corrections reflected the native edit/display
   transition and did not require additional application behavior changes.
   Artifacts: output/issue-dialog-*.png, issue-datepicker-ar-390.png,
   native-issue-ui.cjs and native-date-ui.cjs. These are actual local Odoo views,
   not mocked layouts or live business posting. G4 is closed for the scoped form.
10. All6 PR658 checks passed on initial runtime sourcef1c033cd, including65
    contracting and80 dashboard cases. Final presentation-only delta is now
    frozen for the mandatory final-SHA checks. Independent delivery consumes
    the same financial/concurrency evidence; no repeated load or data cloning.
11. Final hot-path review batched the new journal-line destination guard by
    unique move IDs instead of a search per line. This preserves exactly the
    same posted-link/context checks while avoiding N+1 queries on unrelated
    native accounting batches/POS closures. No new source, permission or amount
    policy; the same regression suite validates the batched implementation.
12. All6 final checks passed on75066434. Independent scoped Alpha GO conditions
    fulfilled:65 contracting cases,80 dashboard cases, source and cumulative
    checks, local native UI and two-cursor proof. PR658 squash-merged as
    0a813514491727a35abc925e9c096a48db6375bf. Module-tree identity checked against
    the reviewed candidate. Bounded policy upgrades onlyabroj_contracting and
    abroj_project_dashboard; no live issue/adoption action will be invoked as
    part of deployment. Source acceptance is GO, protected activation pending.
13. Policy-only CI transport blocked activation: Source integrity attempt1
    timed out10m during fetch of every branch/tag, before any test; retry2 also
    remained in that fetch. Cumulative backend clone took11m58 before passing.
    Diagnosed from completed checkout logs, not an application/test failure.
    Operational G2/G3 reopened and independently approved partial-clone checkout
    `filter: blob:none` with fetch-depth0 retained in validate-pull-request and
    backend cumulative checkout only. Official checkout@v4 action.yml confirms
    the input. Commits/trees/refs/history and every comparison/check/timeout stay
    unchanged; current working tree materializes fully and historical content
    lazily fetches when checked. A fetch error remains a failed check.
    Financial source stays0a813514; no module tree or deployment permission change.
