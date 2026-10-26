# ZATCA POS toggle — QA contract (2026-10-26)

## G0 — approved scope

- **Problem:** TEST3 is outside Phase 2 but Odoo blocks its POS opening because
  its invoice journal has the Saudi EDI format and is not onboarded.
- **User:** POS manager creates an ordinary Saudi register or later enables a
  chosen register for Phase 2.
- **Acceptance:** each `pos.config` has one explicit Phase 2 choice. Disabled
  means the POS opens without the Saudi EDI readiness block, does not force a
  customer invoice, and does not show the ZATCA close summary. Enabled retains
  Odoo's native journal/certificate readiness checks and invoice reporting.
- **Boundary:** QA only; no certificate, OTP, invoice, journal, company, or
  production-data write by this source change. The feature changes no tax,
  amount, payment, accounting move, or EDI document.

## G1 — operating profile

The decision is one Boolean read per POS-opening or checkout interaction. It
does not add records, scans, jobs, or network calls. The existing Odoo journal
and EDI models remain the source of truth. A normal restaurant register has a
small number of concurrent cashiers; no capacity change is introduced.

## G2 — contract and controls

| POS flag | Open POS | Checkout | Native EDI preflight |
|---|---|---|---|
| Off | Allow | Native non-Phase-2 flow | Skip |
| On | Odoo validates its invoice journal | Odoo requires customer invoice | Keep |

The source must never add or remove `sa_zatca` on a journal automatically:
journals can be shared and EDI configuration is accounting-owned. The flag
only scopes the POS behavior. Enabling is denied while a POS session is active,
as already enforced by the view.

## G3 — direct implementation

Extend the existing `baseer_zatca_pos_scope` owner. Reuse Odoo 19 and its
current Saudi EDI module; no library, model, migration, or UI framework is
added. The narrow implementation intercepts the native POS opening guard only
when the flag is off and otherwise delegates to the original method.

## G4–G5 — verification plan

1. Unit test: disabled Saudi POS with an unready ZATCA invoice journal opens.
2. Unit test: enabled Saudi POS with that journal still raises Odoo's redirect.
3. Existing JS scope test: disabled does not force invoice; enabled does.
4. QA browser: TEST3 opens with the flag off; a configured Phase 2 POS remains
   blocked until its certificate is ready.

Status: G0–G5 complete. The implementation adds only a scoped
`pos.config.open_ui()` override: an opted-out POS skips the native
`l10n_sa_edi_pos` onboarding gate, while an opted-in POS preserves it. No
journal, certificate, company, invoice, or external connection is changed by
the source. G4–G5 evidence: Odoo 19 ran both flag paths in a disposable
database, including the installed `baseer_pos_summary` opening guard. G6 is not
applicable: no new data path, queue, or load-sensitive query. QA release and
production are outside this contract until evidence is recorded.
