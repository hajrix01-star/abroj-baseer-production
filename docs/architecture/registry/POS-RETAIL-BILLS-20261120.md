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
