# POS tobacco-tax parity and substitution tolerance

## G0 — scope and acceptance

**Problem.** A protected POS substitution can reject a commercially equal replacement because the POS browser persists a tobacco-tax source-line total that differs by one halala from the server's authoritative computation. Example observed: source `4 × 65.00` persisted as `259.99`; server recomputes `260.00`; replacements `4 × 55.00 + 4 × 10.00 = 260.00`.

**In scope.**

- Make POS and server compute/persist the same tax-inclusive total for tobacco-tax products.
- Keep the existing tobacco-tax business rule unchanged.
- Let every cashier submit a protected substitution when the absolute difference between source and replacement gross totals is within the fixed `0.15 SAR` (15 halalas) tolerance.
- Persist the server-computed source/replacement gross totals, the difference, the configured tolerance, and the normal substitution audit data.

**Out of scope.** Historical orders, tax reports, tax formulas, production deployment, and changing tax legal treatment.

**Acceptance criteria.**

1. For quantities 1 through 15, the POS-visible, stored, and server-computed tobacco source totals agree to currency precision.
2. `4 × 65.00` and `4 × 55.00 + 4 × 10.00` are accepted with zero difference.
3. A difference of at most `0.15 SAR` is accepted for every cashier; a greater difference is rejected.
4. The final decision is server-side, uses tax-inclusive currency totals, and is atomic with the substitution.
5. The tolerance and actual difference are auditable; browser values never decide a financial result.
6. Existing non-tobacco protected substitutions preserve exact-match behaviour unless explicitly configured otherwise.

## G1 — capacity and failure behaviour

- Target normal POS batches with 1–15 tobacco items and an immediate response; no queue or background job.
- One substitution remains one server transaction. A retry must not duplicate an audit record or alter an order twice.
- If an authoritative quote cannot be computed, reject safely with an actionable message; never fall back to browser arithmetic.

## G2 — contracts and ownership

- The server owns tax computation, tolerance comparison, persistence, and audit values.
- The POS client requests/displays the server quote before confirmation and displays the source total, replacement total, actual difference, and fixed `0.15 SAR` allowed tolerance.
- Request payloads contain only selected product identifiers and quantities; they cannot submit price, tax, or tolerance values.
- The existing substitution add-on owns protected-substitution workflow. Tax parity is implemented in a dedicated extension/add-on only if the required safe POS processing hook is outside that workflow; no Odoo core patch.
- No new access level: all cashiers receive the configured tolerance by the business decision of 2026-10-05.

## G3 — direct implementation path

1. Trace the exact POS tax evaluator/asset that produces `259.99` and prove the divergence from the server evaluator.
2. Use a supported Odoo extension point to make the server authoritative for tobacco-tax line totals before order persistence; do not alter the tobacco formula.
3. Extend protected substitution with a fixed `0.15 SAR` tax-inclusive tolerance and immutable audit fields.
4. Add server and POS regression tests for the observed scenario, quantity boundaries 1–15, below/at/above tolerance, retries, and non-tobacco exact matching.

**Gate review (2026-10-05).** The observed production draft stores the source at `259.99`, while the server's direct `account.tax.compute_all` evaluation returns `260.00` for the same source, quantity, company, pricelist, and fiscal position. Replacement products evaluate to `220.00 + 40.00 = 260.00`. This proves a POS-client/server evaluator divergence; it does not prove that the tobacco formula itself is wrong.

**Gate state.** G0–G3 approved for the scoped QA implementation: no tax-formula change, no Odoo-core patch, server-authoritative protected-substitution comparison, a fixed `0.15 SAR` all-cashier tolerance, immutable audit values, and boundary tests. The runtime asset trace remains a required regression investigation before any broader non-substitution POS tax-parity release. No production change is authorized by this document.
