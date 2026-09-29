# HRS1 — Employee services, QA candidate

Installed on `baseer_reports_qa_20260907` at port18070. Open **Employees → Employee Services** (`/odoo/action-653`). Also available from the employee Services page and the existing Financial Record page, subject to their original permissions.

## Delivered behavior

Fifteen approved employee-service types reuse the CSS1 expense/product mappings and company-private providers. Nine service types suggest their seeded provider automatically; manual provider choices remain editable. An unmapped type requires manual choice. Company and SAR follow the active company.

Save draft, approve one native posted supplier bill, then register native partial/full payments. The employee and general registers show source invoice/payment state and remaining balance. Native credit notes provide corrections; full reversal permits service cancellation. Unbilled drafts/canceled records can be deleted; archive retains history. Arabic A4 service statement can be reprinted.

No additional payroll deductions, loans, ledger, automatic bank transfer, or prepaid amortization. Installed Community reports its own invoice `paid` status even when the native payment is not bank-matched; this module does not certify bank settlement separately.

## Evidence

- `../../build-governance/hr_services_checks.json`: 71 passing assertions, rollback verified; approval measured0.457s locally.
- `../../build-governance/hr_services_extended_checks.json`: 56 passing assertions, seven scenario groups, rollback verified. HR-only access/search, actual native payment behavior, partial/full reversal, Arabic PDF, and provider proposals.
- `../../build-governance/hr_services_concurrency.json`: six passing assertions, two independent connections, actual serialization retry and one bill. Disposable clone removed.
- `../../build-governance/hr_services_pdf_preview.png`: visually verified Arabic A4, one page. UI evidence `hr_services_desktop.png`, `hr_services_mobile.png`, `hr_services_provider_proposal.png`; native 390×844 responsive form, viewport reset.
- `preservation.json`: prior QA rows unchanged and original database unchanged. The only committed browser fixture was an unbilled draft, deleted through native UI after inspection.
- `candidate.json` and `verified-package.json`: 14 addon files, SHA256 source/archive/QA-mount equality, installed state verified.
- Independent decision: `../../build-governance/HR-SERVICES-REVIEW.md`.

## Deployment and recovery

Addon archive `baseer_hr_services-19.0.1.0.0.zip` requires the already-tested Baseer payroll, service seed and their dependency chain on Odoo19. It is not a standalone payroll distribution. No vendor or Odoo core file changed.

Backup is recorded in `backup.json`; immutable database dump is `.local-backups/hr-services-20260908/database.dump`. Before any later production rollout, take a fresh database+filestore backup and perform a separate promotion. Restore the paired pre-rollout database/filestore with its prior code for rollback; do not uninstall after issuing bills to erase history.

QA acceptance only; two-connection correctness and one-operation timing are not a production load certification. The repository has no existing HEAD, so this candidate is identified by archive and per-file hashes, not a fabricated commit.
