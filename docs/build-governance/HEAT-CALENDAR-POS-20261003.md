# HEAT-CALENDAR-POS-20261003

## G0 contract / impact

Owner request: implement a unified heat-calendar source during migration from daily summaries to direct POS. Approved nonzero summaries already generate native POS orders. LIVE read-only evidence: 669 approved, all 669 linked to usable native orders marked baseer_summary, no business-date mismatch. Never add summary gross on top of its order. No backfill, reapproval, financial writes, schema change, or Command-center change.

ARCHITECTURAL, narrow financial-reader change. Only baseer_sales_heat_calendar reader, source actions, strings, tests and module version. Prior architecture: COMMAND-CENTER-POS-DAY-20261003 and summary native posting. Original worktree untouched; branch codex/heat-calendar-pos-unified-20261003 from official/main c3dd41d0.

Cycle: summary approval -> existing native order/session/payment/posting -> read-only reporting. Direct paid/done/invoiced order -> read-only reporting. Cancelled/draft excluded. VAT-inclusive signed native amount_total only, preserving refunds. Customer metadata remains summary customer_count; direct POS metric is order count, explicitly named transactions, not unique customers.

## G1 capacity

One active company per RPC. Month plus 8 baseline weeks <= 87 days, <=100,000 visible orders in range, no unbounded order materialization, SQL grouped daily numeric SUM cast to text then Decimal. Existing summary metadata bounded by dates. Assumption <=10 concurrent viewers, target <2s single request at 100k; measured single-request only, no concurrency certification. Existing protected deployment/backups; reversible code reader only. No loads on production/shared QA.

## G2 data contract

Reuse existing protected executive POS query helpers (paid/done/invoiced, session/order record-rule intersection, 07:00–05:00 Riyadh, sale timestamp, 05–07 exclusion, exact SQL decimal). Heat-calendar access remains its own group/dashboard check. Scope to active company only, drop unrelated client context, no sudo. Money from native orders ONLY. Existing daily report used for summary/closure completeness and customer metadata; no monetary fallback for missing native links. Approved zero-sale summary remains visible even without native order. Nonzero summary with missing/inaccessible native link -> explicit unavailable/integrity error, never invent zero. Future POS excluded by now.

Each day has source kind summary/direct/none. If both approved summary and direct POS coexist for same company/day, flag conflict, hide combined amount and exclude from heat/baselines, rather than double-count or choose silently. If direct orders contradict full-day confirmed closure, likewise explicit conflict. Historical summary statuses retained; direct POS day complete only after next-day05:00, current day incomplete, future missing. Unknown absent POS day is missing, not presumed closed. Days containing only off-window sales expose a warning, not a false complete zero. Detail source action opens native pos.order for the day under normal ACLs; zero-summary action remains its approved summary. Direct day source action uses exact window and states; generated summary source follows business date. Preserve target/occasion algorithms and month/navigation/responsive layout.

Frontend retains existing component/template/styles. Labels mention POS including historical summaries and tax; explain direct counts are transactions. Show backend source label/conflict/off-window warning. AR/EN strings in existing translation files, western digits formatting unchanged. No UI library, redesign, animation or new dependencies. Summary shift details only on summary days; direct source detail is orders, no duplicated per-order session payload.

## G3 stack / direct-path decision

G2 clarification after independent review: preserve existing Command-center SAR-only policy. Reject non-SAR reporting companies or visible POS configurations with non-SAR currency using the existing currency helper before aggregation. Never sum currencies or infer FX. Classify generated orders using both baseer_summary_id and source='baseer_summary'; mismatched/missing/inaccessible approved nonzero native links are explicit unavailable errors. Day count label and aria are customers for summaries and transactions for direct POS.

Odoo19 + existing models/executive helpers + SQL + Decimal. No new dependency. Shortest safe path is changing owning heat reader only, not posting summaries again or changing generic daily reports. Validation: existing heat tests plus mixed historic/current POS, VAT/refund, exact decimal, 05/07 boundaries, multiple sessions, zero-summary, conflict, current/future days, isolation/order-session rules, bounded capacity, source actions. Odoo isolated DB only; AST/JS syntax/translations and assets. Independent delivery review before release. QA deployment only through protected policy/Actions; LIVE needs separate explicit request for this change.

## Gates

G0/G1/G2/G3: under independent review; no application edits before approval.
G4: unchanged layout; new localized source/status labels require verification.
G5/G6/G7/G8: not started.

## Append-only operations

1. Preflight: read skill build/architecture/testing and required governance/capacity/accounting references; inspect existing heat reader and executive helper ownership. Result: no native POS read in heat calendar; reuse existing helper avoids new source authority. No runtime writes.
2. Branch: clean task worktree fetched official/main; independent branch created at c3dd41d0. No original workspace or runtime changes. Read planned test/source/translation paths; gate review pending.
3. After independent G0–G3 approval: implement owning heat reader and unchanged-layout source/count/warning labels. Reuse executive capacity/currency/rule/window/exact money helpers. Bound source-action session IDs at1,000 per request. Add api.readonly and active-company clean context. Independent review found nullable source-tag orphan and future/noon summary order fallback risks; corrected null-safe orphan check and required matching native link to be within now/window. Unavailable aria now matches visible dashes. No sales writes.
4. G4 minimal text integration: existing HeatCalendar/HeatDayDetails, Odoo Bootstrap alert and formatter paths retained; no layout/styles/dependency/animation changes. ux-araby used for concise Arabic source labels and unavailable errors. Added AR/EN labels, per-day count meaning and off-window/conflict warnings. G4 pending actual render, not claimed as tested. Testing skill guides 16 new actual persisted POS TransactionCase cases; existing tests mock the new owner boundary. Isolated test intention: fresh baseer_heat_pos_test_20261003 from retained safe snapshot, no-http/cron0, candidate module overlay read-only. Never operational databases; no shared load. Freeze Git source then run suite and record evidence.

## Independent gate decision — 2026-10-03

Reviewer: independent gatekeeper / ERP architecture reviewer (`heat_gate_review`), separate from the application implementer. G0, G1, G2 and G3 are **approved**; this append supersedes their earlier pending status and permits scoped implementation. No remaining entry blocker.

Evidence inspected: this complete contract; `baseer_sales_heat_calendar/models/dashboard.py` and manifest; `baseer_sales_dashboard/models/executive.py`; `baseer_pos_summary/models/summary.py`, `daily_report.py` and `common.py`; build governance, architecture, capacity and ERP references. Native approval is atomic, validates its posting, creates exactly one done order at Riyadh noon, and intentionally creates no order for a zero-sale summary. Existing executive queries intersect order/session record rules and use signed native numeric totals serialized as text; the heat module already depends on their owning module.

G0 approval: scope is a read-only reporting change with an explicit financial cycle and no additional posting or migration. G1 approval: date and order bounds, SQL grouping, isolated measurement and inherited deployment/recovery safeguards fit the narrow reader change; the stated concurrency and performance figures remain assumptions until measured. G2 approval: native orders are the sole monetary authority; summary counts retain their customer meaning, direct counts are transactions in labels and aria, and same-day source conflicts cannot enter heat evaluation or baselines. The recorded currency clarification closes the review finding: use the existing SAR policy, including visible off-window configurations, before aggregation. Every nonzero approved summary must have its matching usable native link; zero summaries remain valid without one. G3 approval: reuse the existing helpers and frontend, with no new dependency, schema or generalized source layer.

Implementation acceptance still requires the planned regression cases, particularly generated-order exclusion from direct classification, mixed-day conflict, missing/inaccessible links, currency, signed refunds, exact decimals, 05/07 boundaries, current/future dates and actual order/session record rules. G4–G8 remain unapproved pending their own evidence and independent delivery review. This review changed only the governance record; it ran no application tests and made no runtime writes.
