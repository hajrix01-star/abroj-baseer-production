# POS-RETAIL-BILLS — native Odoo runtime acceptance

2026-11-20. CONTROLLED, existing Bridge owner. Source base `bcf84e8bc8f1`
(actual frozen QA), branch `codex/pos-retail-bills-runtime`, Bridge `.55 → .56`.
User: enable early bill and split in ordinary POS; minimal changes, no relocation.

Native settings → original `pos.config` flags → original Actions buttons → native
draft receipt / SplitBillScreen → native payment / receipt Continue.
No new model, field, ACL, company rule, calculation, CSS, dependency or screen.
Only Bill/Split are unwrapped in the base ControlButtons template; button sequence,
disabled guards, handlers and existing restaurant behavior remain. Restaurant
Transfer stays restaurant-only. Native linked-order lookup supports retail Continue.
The existing direct draft-print predicate agrees across client/server: restaurant
or explicit `iface_printbill`, plus the original direct-print/session/company/printer
guards. AR/EN error wording reflects the broader eligibility.

## Actual runtime

Source-only preliminary `.18` patch was superseded; testing identified its ignored
extension-of-extension template target. This candidate targets the original base
template. Current `.55` printing also needed the matching retail eligibility change
on both client and server. Both corrections were exercised before acceptance.

Private isolated clone `baseer_retail_bills_20261120` from QA, neutralized; cron off.
Container `baseer-retail-bills-20261120`, private loopback18139, SSH tunnel18839.
QA/current and Live source/data were not modified. Candidate files are mounted from
an isolated temporary directory; no release folder was edited. Existing receipt
layout `baseer_80_customer` and native kitchen/payment behavior were retained.

## Results

- UI: config39, restaurant OFF, both switches saved then page reloaded: both ON.
- Actual Odoo ORM under user2/company scope: all four independent flag combinations
  saved/reopened correctly, restaurant remained OFF; test mutations rolled back.
- Desktop Actions: original Bill/Split buttons in native slots. Mobile390×844:
  same native menu; empty-cart Bill/Split disabled as before. No CSS changed.
- Early Bill on new order: native raster says unpaid, original layout, total3.45,
  tax0.45, no fiscal QR/payment lines. Server accepted exactly one draft job4020,
  statepending; image SHA256
  `0769a87b791bddb85ad76ff87429737a5e025c9814d73ca7487808cd5b259e94`.
- Split by item and then by quantity: water1.15 + salad1.15 + remaining salad1.15.
  All THREE orders paid, qty3, total3.45 and tax0.45 conserved. Native Continue
  returned to the remaining order on desktop and mobile. Final part correctly
  showed New Order rather than Continue.
- Fifteen scoped Node tests passed, including retail/restaurant/disabled direct
  draft predicates and linked-order continuation. Diff whitespace check passed.

Runtime order UUIDs: `5a41f391-ab84-4998-9448-0092cc4ad28d`,
`010f7910-5b5e-4625-9678-78c25034ba9e`,
`320acd1a-fbc9-4c3a-80cc-fed47eb2fc48`.
Local artifacts: root checkout `output/retail-bills-runtime-20261120/` contains
settings, desktop/mobile actions, splits, paid receipts, early raster and proof JSON.

Independent `retail_bills_review`: GO for isolated runtime only, no blocking defect.
Physical printer acceptance was not exercised: queuepending is not printed paper.
No QA/Live promotion is claimed or included; source stays on an independent branch.

## Deeper acceptance — supersedes the earlier limited GO

**Decision: NO-GO for release.** User requested deeper pre/post-payment, Agent,
kitchen and failure-path checks, then reaffirmed minimal changes and maximum native
code reuse. This round changed no application code and reused the same isolated
clone. Candidate remains `abadb06aca85094afc1c5b1fb6ab9ea43fecd278`.

The exact Git module archive was mounted for this round (SHA256
`69c3a3e5dde44ee18084636daf6dba200ad31ba2afb66502c5f986a3da2cbb51`).
The existing architecture/flow above remains valid; no new map or environment.
Native module run: **182 passed, 3 failed, 0 errors, 185 test methods** (199 internal
stats executions). The three failures were fixture assumptions in a populated QA
clone: two assumed no other approved pairing releases, one lacked a free default
cash method. The two release cases passed with pre-existing releases isolated in
their test transactions; the cash case passed separately with a cash method supplied
before opening. The initial full-run result is retained, not relabeled all-pass.
An additional **83 JS checks passed** for cleanup, kitchen recovery and table state;
the prior 15 checks are reused, for 98 scoped JS checks total.

| Finding | Evidence and effect | Severity |
| --- | --- | --- |
| Split after kitchen send loses durable ownership | Actual UI: send qty2, split1. Native baselines become1/1, but durable states remain2/0. Child cancellation becomes `cancel` without a kitchen cancellation record/job. A later change on the original rejects with a stale-state error; cancelling its remaining qty1 creates a CANCEL quantity2. Follow-up cancellation mutations were rolled back. | P1, runtime confirmed |
| Split while kitchen outcome is unknown can sync only the child | Actual runtime native split/history methods plus the actual Bridge sync filter reproduce server-model qty3 versus local qty2: original excluded, child persisted. Transport/model storage are stubs; this is a compositional reproduction, not an actual lost-response RPC run. | P1 risk, exact-method reproduction |
| Pending early bill can retain an obsolete image | Native ORM with a virtual agent/printer: draft total3.45→1.15; a new request with a different JPEG returns the old job/image, `_is_current_draft_bill()` stays true, and claim accepts that old raster. Entire probe rolled back. | P2, runtime confirmed |
| Partial Windows spool failure can be described as `print_failed` | Agent sets `spoolAccepted` only after `PrintDocument.Print` returns. A failure during a later page may have printed earlier pages; a manual retry may duplicate them. No automatic blind retry was found. | P2, source observation; no induced physical fault |

The split/kitchen and draft-queue gaps are inherited integration gaps exposed by
the new retail journey, not proven regressions introduced by the small .56 diff.
Passing the existing suite did not cover these cross-feature cases.

### Pre/post-payment and Agent checks

Actual UI order `7aeaaa5d-d954-4a98-b06a-26fb956e75ba`: unpaid bill job4192 then
paid final-receipt job4193. Native final receipt has the payment and QR; early image
does not. Final remains pending on the offline test Agent. ORM verified: early job
is no longer eligible after payment, retrying the same final image deduplicates to
4193, reprint while the original is pending is rejected, payments are unchanged,
and this unrouted water item creates no kitchen job. Configured copies1, width80.

The full native run covers existing queue leases/recovery, reprint immutability,
invalid images, authorization/company/hardware boundaries, offline kitchen jobs,
destination changes, notes/cancellation reasons and native payment/tax variants.
Independent reviews separately traced kitchen/split and receipt/Agent paths.

`done` means Windows spool acceptance, not observed paper. Agent validates raster
digest/dimensions and prints Odoo's image; it does not calculate financial values.
Receipt/early bill server rules require80mm; kitchen widths are independently
configured. Copies1–10 and raster pagination (up to15 pages) still require real
driver/paper acceptance. The safe `preview-kitchen` CLI exercises the old textual
renderer, so it was deliberately not counted as proof of the current raster path.

No physical paper, cutter, paper-out recovery or actual multi-page partial spool
fault was tested. Browser fallback with direct printing disabled, every combo/
loyalty/promotion split, and real multi-device lost-response splitting are not
claimed covered by the manual journey. No exhaustive-all-possibilities claim.

Evidence in root `output/retail-bills-runtime-20261120/`: `deep-suite.log`,
`kitchen-split-history.jsonl`, `kitchen_split_followups.log`,
`offline-split-proof.json` (runtime native SHA256s included),
`pre-post-print-proof.json`, native repro scripts, and desktop/mobile/receipt images.
QA/current remained `bcf84e8bc8f1-run-44634311872-20261119T230513Z`; no QA/Live
source switch or business write was performed. Test-only UI orders remain in the
neutralized clone; probe mutations used rollback.

Required repair scope stays small: preserve native splitting/receipt/UI/Agent;
repair the missing ownership transfer/uncertain-send guard and pending-draft
freshness contract. Do not introduce a second splitter, printer router or renderer.
