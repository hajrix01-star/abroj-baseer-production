# FL1 independent backend and delivery review

Decision: GO

Reviewer: icons_release. Scope: new read-only baseer_financial_register addon over AR2 6104fc8e6f1d24b3e842f2b43bd9f410840d7759. No application code or MAIN mutation by reviewer. Reviewer prepares fl1_release.py; deployment owner must independently review that helper before use.

## Backend source review

KPI endpoint explicitly rejects cashier and requires native invoice/read-only accounting access. It starts from posted moves intersecting caller filters. Invoice aggregation uses native account.move._search FROM/WHERE with signed company-currency total/residual numeric casts and separate customer/supplier directions and currencies. General journal entries remain register rows but never enter invoice KPIs. No sudo, accounting mutation, new transaction storage or client money authority.

Overdue SQL intersects both the filtered invoice query and the account.move.line._search query, then sums only open past-due receivable/payable payment-term line residuals. Returned drill-down uses the same date/residual/account-type predicate. There is no unbounded record-ID hydration. Native privacy and company record rules remain applied to both model queries.

Source navigation first checks feature permission and caller move read, then follows a fixed installed relation and checks source read before native form navigation. Optional POS-summary/payroll/loan field names were verified against installed addon definitions. No arbitrary model or sudo proxy is introduced. Operation-label fields are nonstored and use native links.

Settled amount means current native total-minus-residual settlement, including credits/write-offs, not bank cash or an as-of historical balance. Read-only row amount remains in document currency; card amount and searchable contributor flag use signed company-currency values. Negative refund contributors remain selectable. Native payment_state is preserved. Empty cards contain real zeros.

## Findings

FL1-R01 source corrected: computed settlement flag originally used document currency while SQL/card totals used company currency. Parent aligned the flag with signed company-currency values and added dependencies; SQL casts total, residual and currency rounding to numeric before arithmetic. Focused tests must prove currency/refund flag/search/card parity.

FL1-R02 source corrected: explicit reserved any! operator rejection now normalizes operator case, matching Odoo19 native operator normalization, and recurses through case-normalized ANY/NOT ANY. Outer model rules remain in force. Zero display is normalized to avoid negative-zero currency text; numeric totals are unchanged.

## Helpers prepared and independently reviewed by deployment owner

fl1_release.py copies all 1156 accepted AR2 files byte-identically and adds only the new addon. It requires reviewed installed dependencies, financial/UI PASS evidence and rollback, source GO, exact frozen PREDEPLOY-GO, pinned read-only mounts and coherent stopped-client pre/post backups. It initializes only the new addon and compares all 368 protected business tables, all existing explicit group/company memberships and all existing role selections without assuming zero assignments. Existing module versions remain unchanged. Helper syntax parsed; no freeze/publish command executed. fl1_github_sync.py separately prepared with exact prior public/source identities, 1156 unchanged baseline files, new-addon-only export and 17-to-18 custom-module inventory; source-only path/secret checks, source lock and verifier remain. It performs no stage/commit/push. Deployment owner independently reviewed both helpers and reported no blocker; this reviewer does not self-approve their own helper implementation.

## Frontend source review

Feature-local list/kanban renderers reuse native paging/search/navigation and share the same KPI component. Native createNewFilters assigns the owned filter its own group; replacement/toggle removes only that group and retains unrelated search facets. No clear-all search operation exists. KeepLast, monotonically increasing request versions, current domain/context snapshot checks and destruction guards prevent stale responses from applying. Refresh is coalesced across native search/model notifications. Loading hides obsolete amounts; errors expose retry instead of fabricated zero data.

Native buttons provide keyboard activation, aria-pressed/labels, focus-visible outlines and reduced-motion behavior. Numeric card strings remain server-owned, in LTR isolation; grid becomes two columns on narrow screens. Native mobile kanban must still be proven in the final browser evidence; a responsive grid alone does not establish automatic view selection.

## Final acceptance evidence

Final replacement accounting evidence passes 62 checks on baseer_ar1_fl1_clean_20260910, a clean MAIN clone with accepted AR2 baseline plus FL1. rollback=true, commit_guard=true and installed_modules_preserved=true; before/after fixture model counts match. Native invoice/refund/receipt signed amounts, current settlements, partial/full/reversed behavior, refund contributor sign, foreign-currency contributor/search parity, dual-model access-aware overdue installment amounts and drill-down, company/currency separation, payroll privacy, cashier/forged-domain denial and native approved POS-summary source/non-duplication are covered. in_payment is a compatibility test using Odoo's native status hook; current installed hook otherwise returns paid. No bank-transit or external-transfer integration is claimed.

Bounded capacity evidence: 180 native invoice fixtures / 360 lines, 199 visible posted moves, one sequential reader; five calls 6.448–8.475ms. Read checks retain source values. This is not certification of 100000 moves or 20 concurrent readers.

UI evidence passes eight observations. Reviewer visually inspected partial-ar.png: two partial customer rows, total200.10, settled35.05, residual165.05; and mobile-ar.png: native kanban and two-column KPI layout. Measured viewport/document widths both480, automatic mobile view confirmed. Arabic/English, source invoice navigation, empty zeros and preservation of native number/reference query after owned-facet removal are documented. Browser UI uses the existing isolated QA fixture database; financial preservation is established solely by the separate clean accounting run. UI language/viewport restored. Stale-response/keyboard behavior is source-reviewed; no synthetic race/load browser test is claimed.

All ten current addon files exactly match the final UI source inventory, and every screenshot/DOM evidence hash was verified. Both source findings are resolved. Source GO authorizes freezing this exact inventory; deployment still requires exact frozen PREDEPLOY-GO and protected MAIN publication. Earlier AR1/AR2 acceptance is reused only for unchanged paths.

The discarded preliminary 62-check run with rollback=false is not accepted evidence. A fixture-created foreign country triggered native localization installation/commit on the isolated QA only. Parent/security agent is rerunning on a fresh isolated clone with an explicit commit guard; no MAIN data was affected. Final acceptance must reference only the replacement clean evidence.

## Final reviewed source inventory

```json
{
  "custom_addons/baseer_financial_register/README.md": "2b2897d671cb5992881205641a23aee2a82c41bf6abc01940aea1c8cb51751d6",
  "custom_addons/baseer_financial_register/__init__.py": "5fd10918e1361ad65b4b41bcd8fb525e659267f47c8c4334ae52530e58908e9e",
  "custom_addons/baseer_financial_register/__manifest__.py": "fe41137a751918002fd60e371f4ffc3c879f3091dfccf145ccdb9fafe8de95be",
  "custom_addons/baseer_financial_register/i18n/ar.po": "9bf1e4a40290e565963286f8b0e6efd7d05c001127b8cee94bde46db98557c1d",
  "custom_addons/baseer_financial_register/models/__init__.py": "d07061010ffa9702c92ed314c725c73e8c0d21e5d49edd30c9a46086e37c183d",
  "custom_addons/baseer_financial_register/models/financial_register.py": "f94b9490b1ec1f98b47e9f6e409881d963fe3e0a0d0242c65d3eb6d69b4db6ca",
  "custom_addons/baseer_financial_register/static/src/financial_register.js": "36051ca83719f23441d535b17b057a1e006c0f7b58a86c05ba4c52012b7e753c",
  "custom_addons/baseer_financial_register/static/src/financial_register.scss": "d2932faf9097721dfefd2a19b38aaf3d0a3d80bbdd3f70a9cdc150aa7255eb24",
  "custom_addons/baseer_financial_register/static/src/financial_register.xml": "b88d63f1aae30987a2c6640f0c2a9fa04b34f4345fa8e1afab7d5b9b6d43d53e",
  "custom_addons/baseer_financial_register/views/financial_register_views.xml": "fd9b4db5f7cda874998c2e98c3a55f155825f47b820b1941c261e1568292141a"
}
```

Release evidence packaging now verifies/copies the UI screenshot/DOM directory into the private release and rechecks it in verify_candidate; the exact accounting harness is also copied and hash-bound. These artifacts are excluded from the source-only GitHub export. Deployment owner authorized and independently reviews this evidence-only helper delta.
