# AR1 independent security and delivery review

Decision: GO

Reviewer: icons_release, independent of application implementation. All source/evidence acceptance gates are complete for the reviewed working source below. This GO permits freezing that source; deployment still requires exact frozen-candidate binding. No MAIN mutation, freeze or deployment was performed by this reviewer. Exact frozen candidate requires a separate PREDEPLOY-GO binding after source acceptance.

## Accepted scope

New baseer_access_roles 19.0.1.0.0 over accepted SD7 commit 4cd5ee3e9bebcd1d85bda2723bf2781643f7f3e7. Owner/General Manager has the reviewed installed administrative group inventory and Settings, with current/new companies. Accountant uses Invoicing, Purchase, Sales and POS. Cashier saves only own draft purchase batches; accountant approves through the native workflow. Both limited roles may approve and record disbursement of employee advances through a separate minimal operational entry, without private payroll/HR/native-loan access. No existing user is reassigned. Native employee names and necessary POS product/contact/tax/stock dependencies remain available.

Only two existing source files change: baseer_payroll/models/common.py adds the exact-loan sudo/object-capability gate, and its manifest changes 19.0.1.5.0 to 19.0.1.5.1. All 1133 unrelated baseline files must remain byte-identical. No salary, tax, installment or accounting formula changes.

## Reviewed controls

Preset assignment requires an existing Settings administrator or trusted sudo environment. Selection replaces explicit grants atomically; role markers cannot coexist and limited grants cannot exceed the expected preset. User-side and inverse group membership writes revalidate. Downgrade removes old explicit grants. Native privilege duplicates are removed; the administrator-only selector precedes native group_ids. Owner inventory is an explicit installed-manager XMLID list; ar1-owner-inventory.json independently confirms 19 installed administrative groups covered and two optional absent references. Future app installations require inventory review. Existing authorized Settings administrators may intentionally customize preset implied groups; this trusted authority is accepted, and preset inventory must be reviewed after customization.

Cashier batch/line own-creator global rules intersect native company rules. Native audit fields cannot be forged through ordinary create/write. Cashier approval is denied even for the already-approved shortcut, native bill/payment navigation is unavailable, and underlying native document access stays denied. Own approved printing checks caller record/company access before private fixed-projection sudo. Computed bill reference similarly returns only the checked linked name. Other cashier reports and references are denied.

The advance bridge verifies role, CRUD/record rules, active/assigned company, active public employee and treasury journal company/type before elevation. Input keys and native link/results are protected, caller context/defaults stripped, and one entry row lock/savepoint wraps native loan create, disbursement and protected link write. The capability requires env.su, exact baseer.hr.loan type and identity with a process-local object, impossible to serialize through RPC. Native active-company checks, employee advisory locks, exact installment rounding, reconciliation authority and accounting lock dates remain unchanged. Native loan links/history/payroll allocations remain unavailable to limited roles. Only amount/state/balance/reference are projected after caller read checks. Actor UID is preserved. Repeat disbursement is idempotent; no external bank transfer is initiated.

Private accounting protection uses conditional global rules on whole moves, every line, payments, invoice-report rows, analytic lines and partial/full reconciliation. Trusted any! predicates exclude existence of any private related move without rule recursion or the erroneous existence of a safe line. Payroll/HR/EOS/correction/advance tags and configured private accounts classify records. Permanent payment classification rejects client create/write/default marker values and remains private after configuration changes. Payroll-account writes invalidate domain caches. Non-POS bank statement data is outside the limited roles.

Partner debit/credit calculations retain native residual/sign/reconciliation semantics but use a one-shot private query sentinel to enforce the caller-visible ledger on the top-level native query. Nested trusted any! predicates remain intact. Search comparisons use whitelisted operators and caller-visible AML SQL source. Raw journal dashboard/statement and account opening aggregates are denied through native field access for limited users; ordinary selection fields remain usable. Owner/manual-user behavior is retained.

## Findings resolved

- R01: accountant invoice group is the accepted narrower implementation, not accounting-manager access; native credit/paid approvals passed.
- R02: public employee name projection is a required dependency; private employee/salary fields remain denied.
- R03: existing Settings-admin customization of role definitions is accepted trusted authority, not limited-user escalation.
- R04: unsafe dotted negative/recursive relation predicates replaced by trusted negative-existence any! predicates, tested with mixed private/public lines.
- R05: partner aggregate/search bypass and journal/opening aggregate leaks corrected; private values hidden while ordinary balances and owner behavior remain valid.
- R06: private-account rule cache invalidation verified after a warmed-cache configuration change and restoration.

No unresolved source security blocker found within the accepted installed-module scope.

## Evidence inspected

Independent security-map agent executed 300 passing integration checks on the final updated isolated QA: 95 role checks, 83 advance checks, 122 payroll-privacy checks. All three JSON records have rollback=true. Reviewer inspected the harness implementations and evidence, including the additional aggregate and warmed-cache cases.

Coverage includes own/cross-user/cross-company access, forged IDs/defaults/context, role escalation and downgrade, native vendor credit and paid/reconciled 115.00 approval (100.00 net plus 15.00 VAT), valid ordinary payments, both limited-role advance postings, exact principal conservation, native loan identity and immutable repeat action. Privacy fixtures use actual mixed untagged salary/payment ledger lines, actual native wizard settlement, payroll/EOS tags, SQL report rows, analytics, partial/full reconciliation, permanent classification and cache invalidation. Partner tests alternate privileged 567.89 and limited zero residuals in the same cache; visible vendor 37.25 and customer 48.75 balances/searches retain native results. Both limited roles are denied protected journal/opening fields through read and fields_get while non-sudo owner retains them.

Final lifecycle has 12 passing checks: clean isolated install with payroll 1.5.1, original business rows/columns and explicit user group/company membership preservation, zero existing preset assignments, update retention/idempotency, uninstall metadata removal/user identity preservation and no pending module operation. Every one of the 21 addon file hashes and two payroll patch hashes in lifecycle evidence matches current reviewed source exactly. Uninstall intentionally removes owned role grants; README requires clearing roles and assigning replacement manual access, retaining an independent administrator first.

Parent supplied final Arabic cashier draft save/reload and POS menu, accountant four-app menu and actual native posted 115.00 bill, owner app inventory and single preset selector/options. Reviewer inspected corresponding text evidence. Final ar1-ui-checks.json reports PASS for nine documented UI observations and matches all 21 reviewed addon hashes. Reviewer verified every attached evidence hash and visually inspected the cashier advance screenshot: native outstanding status, 100.01 principal and remaining balance, three installments, treasury reference, and no salary/history fields. The associated DOM confirms these values. Both roles are exercised in backend advance tests; browser disbursement was performed as cashier. No separate narrow-viewport claim is made.

Evidence limits: report authorization and actual English/Arabic PDF generation passed, but the disposable clone lacks some filestore attachments and wkhtml emitted missing-content warnings; this is not a full visual report-fidelity claim. Advance tests record native loans/ledger, not external transfer or a new full payroll execution. Bounded fixture timings are not a 100-user/10000-record load or concurrent production SLO claim. No MAIN load was performed.

## Release helper reviewed

ar1_release.py requires the accepted baseline, exact new-addon/two-file payroll boundary, already-installed dependencies, final PASS role/UI/advance/lifecycle/privacy evidence, rollback markers and independent GO. Privacy evidence is now included in frozen/hash-verified artifacts. Candidate and archive source hashes are verified, with separate exact-commit PREDEPLOY-GO before publish. Pinned three read-only mounts, coherent pre/post backups while MAIN is stopped, 367-table protected business projection, unchanged existing explicit user memberships and zero role reassignment remain guarded. Only payroll is upgraded while the new addon installs; unrelated module versions/inventory stay exact. Failure leaves MAIN stopped for investigation. No helper blocker remains.

## Reviewed source binding

21 new addon files plus two existing payroll files. Canonical SHA256 of the sorted compact JSON inventory below: `1269a810bd3735820fdbcbd963878a92d9025716da0c19df6a3f81f692a4ffc8`.

```json
{
  "custom_addons/baseer_access_roles/README.md": "81d32b09dce64d9ac3f4bf092e9902c92a46270e6c1cf0df35990b4774ab65e9",
  "custom_addons/baseer_access_roles/__init__.py": "5fd10918e1361ad65b4b41bcd8fb525e659267f47c8c4334ae52530e58908e9e",
  "custom_addons/baseer_access_roles/__manifest__.py": "9d44366b0f6ebad486ab6d92b7f78e1be06dfdf490de2601e5f48001663a4ed2",
  "custom_addons/baseer_access_roles/data/setup.xml": "8570be73d3cc481f181d15a13e2915398932048fdc985bd81d3a9693b1cb2942",
  "custom_addons/baseer_access_roles/i18n/ar.po": "390fb3d6e9a7c032d0f62f2a692b715ba1b5a75d0012d42f26e198175e8326bf",
  "custom_addons/baseer_access_roles/models/__init__.py": "ab83fe6fc5fcf4c840f814756cfee9d36cc435110cd855175ae90eab4426e4e1",
  "custom_addons/baseer_access_roles/models/advance_entry.py": "9fe8cc37b76c0f1c47e5db4bc5be87f9ad7fb3212b51400e7c4aeec2d58f7b65",
  "custom_addons/baseer_access_roles/models/ir_ui_menu.py": "06be4b40d461562f143c27a9980f19c39586504bcfee81d9b931a52f742b760c",
  "custom_addons/baseer_access_roles/models/partner_privacy.py": "158c39635b6c7e545ceb6334035fa22547c56f40f79a16cf25f16a51621fb724",
  "custom_addons/baseer_access_roles/models/payroll_privacy.py": "a8942d809ef7eda2b4e9821b6cab9f964c89e35dd1822113cd5a0f644aaa1c37",
  "custom_addons/baseer_access_roles/models/purchase_batch.py": "ff39b50ad351c2a0dbf8d829db1c8e86889fee2908b30224097d6fc9258e32f4",
  "custom_addons/baseer_access_roles/models/res_users.py": "448b6f547d57af51f71d0239d76a85faa12ffe8ddeb9c91d2fcc158e72377053",
  "custom_addons/baseer_access_roles/models/role_seed.py": "47d0b44032bdf9d7b80828372e47834021343d53d304f2ebda9da6e8a87f9c7e",
  "custom_addons/baseer_access_roles/security/advance_entry.xml": "2754369be8b859fd8d61d7d623da9724bef607bf1c87a4be751bdeed2dca00df",
  "custom_addons/baseer_access_roles/security/cashier.xml": "96e19616288508248fe8f0e3e74f772faba365e7818d92b2369fa28636fddc11",
  "custom_addons/baseer_access_roles/security/denied_rules.xml": "f05e0f655daf1d1916fa9282316bae0041da81551e5dd8bbac1e281f3afa043f",
  "custom_addons/baseer_access_roles/security/groups.xml": "72318e56ebbba283d0a1ac164469c326d543665efd08e48e9051fc54163ffdf3",
  "custom_addons/baseer_access_roles/security/ir.model.access.csv": "ebf3af3a36dd379bb2160c78428d3c47474241a50bfa67d355c7acfbb2a4e475",
  "custom_addons/baseer_access_roles/views/advance_entry_views.xml": "77ff6449cd0a7c82e26a567836a3c351607643cef924694f67f09c6eb67020a3",
  "custom_addons/baseer_access_roles/views/purchase_batch_views.xml": "c49d63616a8b693b8c8e8830158a143d8e08bc9ddeafad2107f393175425dcfb",
  "custom_addons/baseer_access_roles/views/res_users_views.xml": "542ee8c61c234e9d803d750a0975b7f67a511af054e2431a86fe80e1c235b3f4",
  "custom_addons/baseer_payroll/__manifest__.py": "59c6b2817bcb2bf7ff077b600678fdd8d51f52f77471bafae15965e629b38a08",
  "custom_addons/baseer_payroll/models/common.py": "47c924a92fccf126e6261cbc47966595bd8f030b76f0fa9d8f359ac12b401e81"
}
```
