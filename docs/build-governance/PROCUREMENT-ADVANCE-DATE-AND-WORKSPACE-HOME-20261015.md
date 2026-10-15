# PROCUREMENT-ADVANCE-DATE-AND-WORKSPACE-HOME-20261015

## G0 — scope, ownership, and non-goals

This change has two bounded, connected UI outcomes:

1. The Representative Petty Cash screen displays the selected purchase request's
   request date and time together with its existing representative and value.
2. Every backend operation opened from a BASSER workspace card receives one
   consistent "Back to Baseer" control that returns to the BASSER workspace.
   Owner management receives the same return destination through an explicit
   owner landing. The standalone POS UI is not a backend NavBar host, so its
   native exit remains its return route. The control is not rendered for normal
   Odoo applications or for a screen reached outside the workspace route.

The source of the request timestamp remains
`baseer.procurement.request.request_date`; the client may only format it for
display. The BASSER workspace remains the owner of the navigation context and
the only code allowed to set the context marker. No action, menu, company,
record, amount, payment point, accounting entry, or access permission is
chosen by the browser.

Non-goals: changing purchase request sequence numbers, backfilling records,
changing petty-cash funding/settlement rules, exposing a new workspace target,
or adding a globally visible control to other Odoo apps.

## G1 — scale and capacity

The existing petty-cash dashboard already reads at most 100 selectable
requests. The change adds one scalar timestamp to each existing row and adds
no query, sort, aggregate, background job, cache, or retry loop. The workspace
already limits visible items to 40; the ephemeral navigation state has no
server-side persistence. This is a presentation-only delta, so a new
load test is not justified: the changed data access, write path, and response
cardinality are all zero. Existing Odoo and module tests remain the capacity
regression guard.

## G2 — data, finance, security, and identity

* `request_date` is read after the existing company/state/representative domain
  and is serialized only for records the existing dashboard reader can see.
  It is never accepted from the browser or used to calculate the amount.
* Funding submission, idempotency token, company checks, request state checks,
  payment-point checks, and all accounting/settlement behavior are unchanged.
* The workspace RPC continues to derive an approved action from the server-side
  policy allowlist. It does not alter a shared Odoo action record or merge any
  context into its return value: an action can be an ID, a client-action dict,
  or the company-pool dict with protected defaults. A central front-end
  navigation service carries an ephemeral, presentation-only state after the
  approved card has been opened. That state is never an authorization proof.
  The client can request the known workspace action; normal Odoo ACLs still
  decide whether it can open it.
* `request_date` is a server UTC datetime. The client parses it explicitly as
  UTC, renders it in the active Odoo user timezone and UI language, and forces
  Latin digits (`0`–`9`) for readable operational codes/times. Labels are
  translated through Odoo's translation system in Arabic and English.

## G3 — UX and failure behavior

The selected-request area remains one responsive grid card: request value first,
then a concise labelled request date/time. Dropdown rows include the same date
for disambiguation. Long names wrap without overlapping numeric values.

The home control is a labelled, keyboard-accessible toolbar button using the
existing Odoo button/icon system. It has a translated accessible label and
returns through the action service without browser history manipulation. The
central service activates only after an approved workspace card succeeds,
survives descendants of that operation, and clears on a different Odoo app or
on the workspace landing page. It therefore covers client, act-window, and
company-pool actions without rewriting their source context. Owner management
can return to an explicit owner landing with its configuration button, avoiding
the former automatic-management loop. On action/RPC failure the existing safe
Odoo error path remains in control; no error details are exposed.

## G4 — implementation contract and acceptance gates

The implementation is central rather than copied into feature pages:

* `baseer_basser_workspace` owns a single ephemeral navigation service,
  activates it only from `openItem`, and provides the single navbar extension.
* `baseer_procurement_requests` adds the raw request timestamp to the existing
  dashboard contract and formats it once in its client component.
* Existing `Dropdown`, Bootstrap/Odoo button styles, `_t`, RTL direction, and
  the module's responsive grid are reused. No third-party dependency or new
  design system is introduced.

Acceptance requires:

1. A dashboard test proves the timestamp is returned for an eligible request
   without changing its value or eligibility.
2. Workspace tests prove the central state activates for client, act-window,
   and company-pool responses without rewriting their action data, clears when
   leaving BASSER or returning home, and the NavBar getter proves the control
   is visible only for an active BASSER operation. The owner route proves the
   explicit landing page prevents a management-return loop.
3. Client tests cover an Arabic and English datetime, a UTC value crossing a
   local midnight boundary, Latin digits, translated labels, and a narrow
   viewport/dropdown wrapping rule; Python/XML/JS checks pass in CI.
4. Independent G0–G3 review confirms no route can bypass the server allowlist,
   company scope, or finance workflow before code is written; an independent
   candidate review is required before release.

### Independent G0–G3 gate review, 2026-10-15

Initial review found G2/G3 incomplete because the three existing action return
shapes could lose protected context. The revised contract above replaces the
unsafe context merge with a client-only ephemeral service, states its lifetime,
and makes UTC parsing/test cases explicit. Reviewer: independent candidate
review. Decision after revision: **GO to implementation**, contingent on the
listed client and server tests; no QA or production deployment is implied.
