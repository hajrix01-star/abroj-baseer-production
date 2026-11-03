# Contracting voucher workflow — 2026-11-03

## G0–G3 draft / live work ledger

Baseline761eb0c99; prior runtime0a813514 and CONTRACTING-ISSUE-20261103 reused.
ARCHITECTURAL: source linkage, native recognition/settlement, budget allocation,
company isolation and guarded historical remediation. User authorized implementation,
review of ALL contracting vouchers and evidence-backed linkage; no invented tax,
party, recognition or approval of an unapproved project budget.

G0 scope: payment direct expense / existing supplier bill settlement / advance;
receipt direct earned income / existing customer invoice collection / advance.
Preserve separate subcontractor supplier-refund semantics. Draft -> issued pending
accountant -> reviewed purpose + native partner/project/source/budget -> atomic
recognition if needed + single native payment + reconciliation -> immutable evidence.
Legacy posted payments retained; add missing recognition only with documentary
evidence, reconcile existing open lines; ambiguous records remain explicitly pending.
Native reversals/credit notes correct posted history, no silent financial rewrites.

Acceptance: repeat/concurrent request has one payment and one recognition source;
partial settlements bounded by residual; same company/currency/partner/project;
payment and collections never become recognition by themselves; native expense
actual and recognized income distinct from commitment margin/cash; budget detail
linked to analytic recognition lines, no manual actual duplication; backend Decimal
two-decimal input validation and native tax/period/reconcile authority. AR/EN native
UI, RTL/LTR/Western digits/small-screen, no added dependencies or global formatters.

G1 assumptions pending live inventory: owner-scale ERP, <=10 concurrent accountants,
<=1000 vouchers/month and <=100000 retained vouchers, pagination/bounded audit,
one atomic document per request, native retry, no production load. Reuse existing
isolated fixture DB and native tax tests; targeted new two-request race only if new
lock/reconciliation path is not covered by prior issue proof. Recovery through
protected deployment recovery pair and native reversal for operational postings.

G2 proposed reuse: existing Odoo19 invoices/payments/reconcile and current canonical
cost linkage; workflow lives in project-dashboard integration if budget model remains
its owner, avoiding a contracting->dashboard dependency cycle. Indexed immutable
voucher-to-recognition linkage; source row locks and native open-line locks; no sudo,
context privilege switches, party-name inference or automatic historical payment.

G3: retain Odoo19 ORM/account native components, existing native date widget and
translations, Python Decimal. No library/install/new service. Commands: targeted
module runtime + dashboard/contracting regression, native dialog preview, source CI;
independent ERP gates/release acceptance before protected Actions activation.

Independent gate owner: erp_review. G0/G1/G2/G3 currently IN REVIEW; application
implementation prohibited until reviewed. Root backend; issue_ui native views and
translations; issue_tests new focused suite. No overlapping ownership.

### Operations

1. Read build/architecture/governance/accounting/scale and orchestration references;
   reused prior registry/runtime evidence and existing independent agents. Initial
   fetch via absent origin failed harmlessly; official/main fetched, isolated branch
   codex/contracting-voucher-flow-20261103 created from761eb0c99. Root tree untouched.
2. Narrow reads: contracting document/voucher/payment/cost + accounting_issue,
   dashboard budget/actual metrics, existing issue fixture. Live read-only inventory
   next: all companies/projects/vouchers/payment lines/recognition docs/budget sources.
   No operational writes before bounded evidence-backed remediation is reviewed.
3. Independent erp_review approved G0–G3 subject to preserved original payments,
   explicit purposes/partners/taxes, native invoice+payment+reconcile atomicity,
   company/currency/project/account/residual checks and guarded legacy RPCs.
   Initial scope permits one invoice per voucher (multiple vouchers per invoice);
   partial invoice settlement allowed, voucher overpayment rejected. Advances
   remain unapplied until explicitly linked. Supplier refunds use supplier AP,
   not customer AR or revenue. Missing original partner blocks automatic linkage.
   Direct recognition uniqueness applies only to created source, never installments.
   G0/G1/G2/G3 now APPROVED for this slice; no dependencies added.
4. Live inventory found7vouchers in1project:2cancelled,5posted, all native partners
   present.2container payments1200;2contract advances3500;1customer collection5000.
   No native recognition invoices or custom costs. Budgetline14 explicitly1200
   containers, detailtotal170780, comparison0. Owner asked asynchronously whether
   advance evidence exists and whether detailed budget should be approved.
   Retain draft budget absent approval; no fictional revenue recognition.
5. Existing fixture environment will be reused: new reconciliation path introduces
   invoice-residual races not covered by prior source-issue race; actual owner
   inventory7documents, test2simultaneousrequests on samevoucher and sharedinvoice.
   No new DB clone or general load. Read native installed payment/reconcile/
   analytic-line source; native components are the named G4 design catalog.
6. Implemented dashboard integration with native review, explicit purpose,
   immutable original payment/recognition, unique source links, original invoice
   settlement and budget-to-analytic metadata. Native UI/PWA AR/EN fields and
   source links reuse Odoo components. No frontend financial arithmetic added.
   Reviewer identified and source review closed4blockers: originalpayment lifecycle/
   line protection, issuer separation, hidden-invoice advance bypass, restricted
   field reads at nonaccountant creation. Independent supplier refunds excluded
   from customer collections; preserve native supplier AP direction.
7. Owner approved proposed historical treatment without additional attachments,
   and explicitly approved170780 comparison budget. Exact manifest only, no global
   auto-classifier. Containers1200 expense/no VAT deduction,3500supplieradvances,
   5000customeradvance; original payments and clearing remain unchanged.
8. Test r1 exposed local filestore mistakenly mounted read-only; corrected mount,
   no application change for that setup. r2 reused UI fixture whose users were in
   Arabic, blocking two language-disable tests; reset local fixture language only.
   Existing HTTP voucher fixture lacked newly mandatory purpose; updated input.
   Source-cost reuse case aligned to confirmed UNPOSTED cost, with posted cost
   explicitly using settlement. r3 baseline commitment assertion included the
   fixture's existing1000 subcontract; corrected expected total, not accounting.
   Evidence output/workflow-tests-r*.log. G5/G6 evidence still collecting.
9. Local r3 passed117/118 with only the fixture commitment expectation above;
   r4 reran that corrected case successfully (0failures/errors). Union proves
   all27new workflow cases plus91existing dashboard tests, including nativeHTTP.
   No remaining application failure. Native preview reused same isolated DB.
10. Two independent RR cursor proofs passed with native retrying: same direct
    voucher returned identical invoice218/payment45 to both requests (attempts1/2),
    actual100 once. Two vouchers consuming invoice217: one payment46, second
    retried then rejected on exhausted open lines; original invoice residual0,
    actual100 unchanged. Expected serialization conflicts recovered without deadlock.
    Evidence output/verify-voucher-concurrency.py and voucher-concurrency.log.
11. Actual native dialogs EN1280/AR390 passed overflow, translation and Western
    digit assertions; mobile screenshot visually reviewed. Test initially expected
    the form title rather than native action title, corrected selector assertion
    without application change. Artifacts output/voucher-review-* and native-voucher-ui.cjs.
    Native tax, locked-period, independent refund, original-payment freeze and
    reversal, missing-partner, issuer separation and hidden-field RPC cases passed.
    G4/G5/G6 implementation evidence ready for independent acceptance.
12. Bounded operational manifest prepared in ops/production/review_contracting_vouchers_20261103.py:
    exact5posted voucher/payment IDs,2cancelled preserved, private-company context,
    existing purchase journal415/cleaning expense3554/category14, dry-run default.
    User approval audit, native workflow actions, comparison-budget action, original
    fingerprint/payment-count/actual/budget/profit assertions and single finalcommit.
    Execution waits for independent review, finalCI and protected runtime activation.
13. Independent delivery accepted native UI,27cases and both races onbc6f03508;
    G4/G5/G6 closed. Added requested operational-only precommit guard: contract
    commitments17000, no unrelated/unreviewed project costs, exact2container cost
    sources matching recognition bills, finaltotal18200/commitmentmargin156800.
    PWA caption clarifies this margin is after commitments, distinct from earned
    profit; KPIlabeltestpassed, financial formulas unchanged. FinalSHA CI pending.
14. Final acceptance check reopened G2 for uncategorized existing supplier bills:
    project actual could be correct while category actual remained incomplete.
    Independent reviewer approved the shortest remedy: when project categories
    exist, validate each original expense AML and matching AAL category before
    settlement; allow multiple valid categories, reject missing/inconsistent tags
    before payment creation. Do not rewrite posted classification in this wizard.
    Added one focused rejection/multi-category test; historical direct invoices
    remain unchanged. Only this delta requires fresh scoped validation/finalCI.
15. All5required CI checks passed on4223c559, including27new+91existing runtime
    cases. Added budget validation delta then tested28workflow cases locally,
   0failures/errors (output/workflow-tests-r5.log). New case rejects unclassified
    posted invoice without a payment, reverses its synthetic source natively,
    then settles50/50across2categories with actual100/categorysum100. Existing
    same-invoice race fixture already carries valid budget metadata; no locking,
    amount or UI change. Payment-count operational assertion scoped tocompany56
    to avoid unrelated companies' concurrent cash movements causing false failure.
    G2 amendment approved independently; finalSHA CI pending before activation.
16. All5final checks passed on86d6194d (runtime119cases:28new+91existing).
    Independent scoped delivery GO conditions fulfilled. PR660 squash-merged as
    a502e5bd40b8c709555091e8d5e2b0d472c177b8; module and operational-script identity
    compared against reviewed86d6194d with emptydiff. Named policy upgrades only
    abroj_project_dashboard, version19.0.1.9.0. Native core and prior contracting
    module unchanged. Protected activation and bounded operational review pending.
17. Protected approval41696403861 and deployment41696477386 succeeded for
    a502e5bd4. Read-only operational dry-run passed exact originals. Apply failed
    inside native baseer_native_spend validation: company56 requires spendroot2
    in addition to project84. Whole transaction rolled back; independent read
    confirmed costcount0, all5reviewflagsfalse and original payments unchanged.
    Initial mapping missed this existing registry boundary; no native guard was
    bypassed and no partial historical write persisted.
18. G0–G3 reopened and independently approved native analytic.mixin/widget for
    both voucher review and standalone cost issue. Shared backend validator:
    valid reviewed JSON, active readable company/shared accounts, project100%,
    one account per root/allocation; native posting owns mandatory-plan checks.
    Small bill-line preparation hook reuses existing tax/post engine and permits
    dashboard budget metadata without circular dependencies. Integration test/CI
    installs existing baseer_native_spend (source unchanged), reproduces mandatory
    spend and combined multi-plan analytics. Same fixture DB, no cloned production.
    Reviewer approved explicit account12 'maintenance/operations' for exact2
    container services using cleaningexpense3554; no supplier-wide default orVAT.
19. Implemented shared reviewed-distribution validator and nativeMixin on both
    wizards; core prepare-line hook keeps the same native tax/post engine and
    dashboard adds budget category before analytics. Integration32cases with
    installed baseer_native_spend passed (native-analytics-tests-r2.log). First
    run exposed nativeMixin rounding/raw-string behavior before action validation;
    fixed pre-sanitize validation before native rounding on create/write. Expanded
    malformedJSON []/0 and write paths passed targetedr3 (0failures/errors).
20. Actual native multi-plan picker selected project+spend in bothwizards at
    EN1280/AR390. Synthetic admin lacked analytic permission; owner LIVE read-only
    check confirmed all native accounting/analytic groups and read permissions.
    Added analytic group to synthetic admin only. Test adapted native mobile
    readonly many2one input to selection dialog, no application change. Native
    popup had8pxoverflow at390; shared scoped mobileSCSS bounds it to372px, all
    actual rectangle/scroll/Western-digit checks passed. Screenshots native-analytic-*
    and script native-analytic-widget-ui.cjs retained; AR screenshot visually read.
    Unchanged locking/race proof reused per independent review. FinalCI pending.
21. All6final checks passed on8ef909c4c, including65contracting and123dashboard
    cases withnativeSpend (32workflow). Independent delivery accepted exactSHA.
    PR662 squash-merged as9a9f812a3ef88c6599547ed9ad3b757b0b30a1d9; bothmodule trees
    and operational manifest match reviewedcandidate. New named policy upgrades
    onlycontracting19.0.1.8.1/dashboard19.0.1.9.1; nativeSpend source/config unchanged.
    Protected activation and approved exact historical review remain pending.
