# Doha owner-summary coverage — investigation and gates

## G0: corrected scope

The owner clarified the cases belong to Doha Consumer (company 3), not ARZ (company 1). Do not alter posted moves or Baseer billing report modules. This investigation concerns the financial dashboard's isolated reader; preserve its existing authorization and fail-closed guards. The owner requires an isolated copy containing the actual Doha cases and a separate explicit approval before production deployment. Cases span October and November and include partial bill settlement, rounding write-offs and an erroneous payment with a bank reversal; they are not interchangeable with six arbitrary `account.payment` IDs.

## G1: capacity and safety

Reuse existing bounded scans and pagination. Previous 20-payment synthetic measurement is not proof for this amended scenario. No load on shared or live systems; real-data acceptance needs an isolated, consistently restored copy. A rehearsal helper is locked pending review of resource caps, source immutability, read-only live fingerprinting, permissions and export evidence.

## G2: accounting and company contract — bounded design approved for implementation

Authoritative facts are posted liquidity lines, move and payment company IDs, their actual reconciliations and explicit reversal links. Names and visible journal sequences are not globally unique. Apply the active company consistently to census, sources, totals, details and exports, including when multiple companies are enabled. A partial payment to an open invoice is not inherently a write-off; preserve its true remaining balance. Count only evidenced actual cash flow. Reversal handling must respect both cash directions and dates, including reversal in a different period, without duplicate claims or pretending the original payment did not happen. Preserve billing report behavior. Company overlap is a hypothesis, not yet a proven root cause; static review found company filters and internal IDs.

Difference handling must be anchored to posted accounting evidence and currency precision. The existing split-payment reader proves the exact cash witness and keeps all related allocations in the unconfirmed classification; it does not call a difference rounding or create an expense. Independent accounting review distinguishes that cash proof from approving a write-off policy: no arbitrary monetary threshold is implied or authorized. Any accounting categorization of a difference requires its own evidence and policy. Fail closed on missing proof or permissions.

Independent accounting review: the owner's reversal case is linked through Odoo's `reversed_entry_id`. A bounded design may admit a one-to-one posted reversal only after checking company, currency, source and reversal line visibility, opposite cash amount and account, journal, dates and duplicate claims. Model original outgoing and return on their actual dates and journals, not as sales; use signed net payments and retain separate details. If the links, permissions or exact allocation are unavailable, remain incomplete. The report's existing positive-only reducer is unchanged; a dashboard-private arithmetic adapter and a separately reviewed private collector are required. The independent reviewer highlighted period and return-only cases as mandatory. No approval of live release or treatment of other reversal shapes is implied.

## G3: direct path and validation — approved for bounded implementation

Use the existing Odoo stack and dashboard reader without new packages. Add focused accounting and multi-company tests, including identical display names across companies, journal/date filters, true partials, small and unsupported differences, reversal across periods, ACLs, stale revisions, and matching summary/detail/exports. Verify billing reports unchanged. Before real-data acceptance, identify the actual Doha source records independently, verify the isolated copy and compare each amount and reconciliation against the frozen reference. An Odoo shell snapshot is read-only evidence, not user-level authorization or proof of isolation.
