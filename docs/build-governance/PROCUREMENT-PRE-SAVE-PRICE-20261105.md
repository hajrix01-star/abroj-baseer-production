# Procurement price before first save — 2026-11-05

Scope: editable unit price for a new catalogue cart, consistent with the existing draft editor. A change belongs to this request only. Existing confirmed-handover restrictions remain. QA acceptance must not save or confirm an operational request.

G0: user requested the feature; default scope is new orders and drafts. The existing draft editor already accepts planned prices. No change to last purchase price, custody, stock, accounting, or receipt confirmation.

G1: reuse the existing bounded cart and quote/create RPCs, debounce and response sequencing. No added network call, query, index, scheduler, or capacity assumption. No new load environment is justified for this local payload extension.

G2: server remains authoritative for decimal validation, totals and rounding. New optional raw unit_price must be validated consistently by quote and create. Omitted price retains legacy behavior. Supplied price participates in duplicate-submission identity, and retry must not duplicate requests. Backend contract independently reviewed and approved: explicit nonnegative price including zero; blank/null invalid; omitted price keeps exact legacy canonical payload. Only supplied prices participate in price-aware idempotency.

G3: use existing Odoo/OWL components, decimal helpers, PO translations and existing tests. Direct implementation in the current quote/create path is sufficient; no dependency or new service.

Acceptance: quoted total matches saved isolated fixture; malformed/negative/nonfinite/excess-precision inputs rejected; explicit zero and omitted price handled deliberately; default price is not changed; quote remains read-only; legacy callers and duplicate retries retain behavior. Frontend uses a visible bilingual unit-price label, raw strings, server totals and stale-response guards. Independent review and protected QA precede production.

Status: inspection and contract review; no operational order modified.

Implementation: shared server price/line/aggregate decimal validation in quote and create; explicit prices alone extend the canonical identity. Price fields remain request-local. User confirmed new orders and drafts, request-local price only. Frontend62 tests passed; the same tests fail4 cases on the prior source. XML parsing and existing LibSass compilation passed (29721 bytes). Independent source review found a line/aggregate extreme-value mismatch, corrected by the shared amount helper; final review and isolated Odoo CI pending. No operational order saved or confirmed.
