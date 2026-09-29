# AR2 independent role-form fix review

Decision: GO

Reviewer: icons_release; no application changes, browser interaction or MAIN mutation performed. Scope is the three-file delta over accepted AR1 98f9d4dced9f7a844d3d44e63f89d8d0d8218664, with roles module 19.0.1.0.1. Reuse AR1 accepted accounting/privacy architecture and evidence; this change does not touch financial logic or those controls.

## Root cause and source review

Native mail notification preference inbox adds mail.group_mail_notification_type_inbox. The original limited-role allowlist rejected this technical group when saving a user, despite permitting the business preset. Native mail_groups.xml defines it without implied application grants. The fix adds exactly this group to the existing optional multicompany allowance, without broadening accepted application permissions.

Role selection preserves the user's inbox preference when replacing explicit application grants. Existing-user writes preserve each user's current preference in mixed batches, inside one savepoint. Guarded role/group/company fields still require an existing administrator before processing. Native self-service notification-only writes use Odoo's existing self-write sudo boundary; no custom preference-based bypass is introduced. Direct role/group/company writes and combined preference/escalation payloads remain subject to the original guards and membership validation.

Onchange computes the same preset groups for native form preview. The native role radio becomes readonly while a preset is selected. The native group widget remains interactive because readonly rendering suppresses Odoo implied-group placeholders; original server guards continue rejecting grants outside the selected preset. Clearing a preset returns to manual internal rights and retains the technical preference. No arbitrary technical-group scan or blanket allow is introduced.

## Release helper review

ar2_release.py restricts source to exactly the manifest, res_users.py and user-form XML changes; all 1156 source filenames remain and 1153 files remain byte-identical. Requires final role/UI PASS evidence with integration rollback, independent GO and exact frozen PREDEPLOY-GO. Updates only the already-installed role addon to 1.0.1; payroll and unrelated module versions must remain unchanged. The protected table inventory is the original 367 plus baseer_advance_entry (368). Existing explicit user groups, company memberships and all existing role selections are compared before/after. Pinned read-only mounts, maintenance lock and coherent stopped-client pre/post backups remain intact. No helper blocker found.

## Acceptance evidence

Final focused role/preference/escalation matrix now passes 55 checks with zero violations and rollback=true, covering 32 create shapes and 23 preference/transition/negative checks. Final ar2-ui-checks.json passes five observations: actual new accountant with inbox notification saves/reloads, three selected companies and preset/application selections persist, native administrator radio remains disabled, and inbox preference remains selected. Reviewer inspected screenshot and DOM and verified every evidence hash and all three source hashes. Source GO permits freezing this exact reviewed delta; separate exact frozen-candidate PREDEPLOY-GO remains required. No unrelated full backend/lifecycle suite is required for these unchanged paths.

## Reviewed working source

```json
{
  "custom_addons/baseer_access_roles/__manifest__.py": "6b2a0f49d1e6b08ed3d143ed368d29acfd47530f5145cfd61879f2b36c28d695",
  "custom_addons/baseer_access_roles/models/res_users.py": "1797a83521d5faac9b8c68ddf2c691654f676244ed2f28343af1fa19f52c8641",
  "custom_addons/baseer_access_roles/views/res_users_views.xml": "1514396e5df4a65ebd17fee1355035decd7a926b6da636eefac40f308dff0f8e"
}
```

