# FA2 POS remediation — G2 delta and execution log

2026-09-09. Owner: audit_sales_reports. Root approved this correction slice and confirmed G0–G3 approval before application edits. Uses alpha-build-team's existing Odoo/Decimal/atomic transaction contracts. No additional libraries, financial ledger or JavaScript computation.

## Reviewed correction contract

POS and accounting manager, in the active company, supplies a reason. A single transaction locks the original summary and company, verifies original business date remains open, verifies every owned original move remains posted and unreversed, and rejects any reconciliation to records outside the owned original move set. It reverses the original owned moves using native reversal, retains those reversals and original source, marks the original cancelled for correction and creates a linked replacement draft for the same business date/shift. Repeated correction returns the same replacement. No external settlement is silently unreconciled; no locked date is shifted. An original receipt-only native reversal remains allowed and does not cancel sales; later full correction of such a source is rejected with an explanatory message.

Cancelled summaries are excluded from active overlap/unique-period rules and every live daily/archive/WhatsApp aggregation. The replacement remains a draft until reviewed and approved; this temporary incomplete/missing status is explicit. Source-to-replacement and reversal links remain available for audit. Original summary monetary values are retained.

## Other changes

- SALES-001: upgrade repairs only dedicated summary configurations with an invalid non-service product by assigning a separate copied service product. Never converts an existing stock product or rewrites its history. Repeated upgrade is idempotent. Product-type changes that would break a dedicated configuration are rejected. Cause was not proven in FA1; no speculative cross-module hook edit.
- SALES-003: archive missing-shift projection uses the daily coverage authority, including confirmed half-shift closures. Provide closure drilldown and avoid misleading WhatsApp missing-shift warnings.
- Protect original owned accounting moves/lines against direct reset/edit/delete; block unreviewed session-income reversal, preserve native receipt-only reversal. Server-only identity token authorizes internal generation/correction, never a JSON boolean.

## Validation target

Exclusive `baseer_fix_sales_20260909` clone, isolated addon source snapshot provided by root. Tests: upgrade actual product29 configuration without mutating stock product; current approved-source tampering and forged context/link denial; native receipt-only reversal; correction1150→replacement230 and exact income/VAT/cash/daily values; late injected reversal failure leaves original and all document counts intact; repeated and concurrent correction create one replacement/reversal set; closed date/external settlement rejection; half-closure/archive/message parity. Previous regression suite as applicable. No QA/main writes, no external message sends.

## Live log

1. Read FA2 mandate, current POS models/views/security/migrations and relevant native reversal flow. Reused FA1 source mapping rather than repeating the full audit.
2. Sent proposed correction lifecycle to root; root approved its limited scope. G0–G3 approval received before code. This G2 delta records that agreement for the independent gatekeeper.
3. Native Odoo prevents a paid/done POS order becoming cancelled even after its accounting is reversed. Root approved a narrowly bounded private extension: after exact native reversal and source cancellation, `_mark_summary_corrected` validates the internal identity token, summary/order identity, reversal coverage and posted status, then calls ORM above the native POS write layer for `state='cancel'` alone. It preserves all original lines/payments/totals and history. RPC cannot call the private method or forge its token. A failure after this state transition was injected and rolled back with every accounting count and both states restored.
4. Exact reversal validation checks one counter-entry per original, original business date, company/journal, and zero net balance and foreign amount per account/partner/currency for each original/reversal pair. Native POS default analysis excludes cancelled orders. Verified its total 1150 → 0 pending review → 230 after replacement approval.
5. Independent security review identified the replacement-period invariant; explicitly prevented editing its date, shift or schedule and prevented deletion of linked replacement drafts. Both receipt wrapper models also guard link/amount mutations and fabricated creation so native move discovery cannot silently lose an owned receipt.
6. Isolated upgrade executed with product29 unchanged (`consu`) and replacement service268 assigned to configuration1/company6. Repeated repair created no additional product. Existing approved entries and reversals acquired protected ownership through migration.
7. Final isolated source is recorded in `sales-freeze.json` and `sales-source.json`. 357 checks passed, including three actual concurrent races, 160 legacy regressions and independent ERP report parity. No QA/main writes and no external messaging. Root owns integrated upgrade and desktop/mobile review.
