# OpenHRMS 19 evaluation — NO-GO

Requested Cybrosys/OpenHRMS vendor evaluation installed successfully on QA, but financial acceptance failed. No calculator, new payroll workflow, bank transfer or real salary was implemented/processed.

Pinned official commit c70e3f54b50442f46faed15f2643aed278b3fb37, four modules391 byte-identical source files in third_party_addons/openhrms_19. Full manifest identifies the package and six evidence files. No vendor edits, no Baseer guard addon, original QA compose restored.

## Proven defects
- Unmodified payslip approval crashes: missing hr.payslip.net_wage referenced by loan accounting.
- Process-only characterization shim (not shipped) then demonstrates repeated approval creating two salary journal entries and replacing the source link.
- Posted payslip source still editable; cancellation deletes its latest posted journal instead of recording reversal.
- Loan cancellation can retain paid installment flags; source shows disconnected salary loan splitting hook and separate child/company permission gaps.

See ../../build-governance/PAYROLL-VENDOR-AUDIT.md and payroll_p1_vendor_checks.json/.py/.log. Seven observations are defect characterization, NOT seven acceptance passes. Both mail.template.send_mail and mail.mail.send patched during tests;2 template sends suppressed. All fixtures rolled back,0 slips/loans persisted.

## Safe state
QA stayed stopped during installation/tests. Verified0 connections before restoration, financial/users/company fingerprint recorded. Evaluation DB retained as baseer_payroll_eval_20260908 with ALLOW_CONNECTIONS=false; no service points to it. Its filestore copied to matching directory in existing odoo-data volume. Original QA recreated from preinstall dump; same76moves/6users/5companies and byte-identical aggregate fingerprints before/after. Original main baseer_dev read-only verification:0 selected payroll modules installed.

QA service reports_qa restarted on18070 with original addons-path. Source/vendor evaluation files retained for a corrected upstream version or an independently reviewed focused extension. Do not enable evaluation connections or expose a service until its finance defects are resolved. No unsafe payroll appears in restored QA or main.

## Remaining work
Full requested payroll remains pending: safe base engine integration, salary split calculator, explicit leave/partial-period rules, loan recovery/deferral/reversal, real native payment reconciliation, batch signature printing and company permissions. A design draft exists in PAYROLL.md but was not approved or implemented. Fixing this is a bounded financial integration project, not merely enabling settings; user preference for minimal code prevents representing it as a ready package.
