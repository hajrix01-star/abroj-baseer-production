# AR2 notification preference and role-form fix

The native In Odoo notification preference adds mail.group_mail_notification_type_inbox. AR1's strict role group allowlist rejected that technical group, so saving a new accountant/cashier with inbox notifications failed. The exact error was reproduced in the isolated browser and backend. Ordinary email-preference users were unaffected.

Allow only this existing notification group in addition to the prior role grants. Preserve each user's preference when changing or clearing presets, including mixed bulk updates. Keep native own-preference handling and all existing administrator/group/company guards. Selecting a preset now previews its native application groups immediately; the native User/Administrator radio remains read-only while a preset is selected. Native application widgets stay intact because making that widget read-only suppressed implied-right labels.

Scope: three files in baseer_access_roles, version19.0.1.0.1; 1,153 other accepted files unchanged. No accounting, employee-advance or salary-privacy logic changes. Existing users and role assignments are preserved during upgrade.

Evidence:55 focused rollback checks covering inbox/email creation, one/three companies, admin/self notification toggles, privilege-escalation denial, other-user denial, downgrade/manual-clear/bulk transitions and onchange previews. Five Arabic browser checks include actual new accountant with three companies and inbox preference, save/reload and retained permitted application rights. No user invitation was sent; UI fixtures remain isolated.

Release commit, source hashes, independent review, coherent backups and original-data preservation are recorded alongside this handoff. After upgrading, refresh the user form and save the selected preset normally; disabling inbox notifications is unnecessary.

Deployed original source `6104fc8e6f1d24b3e842f2b43bd9f410840d7759`; HTTP200,368 protected tables and current security assignments exactly preserved. GitHub `4124200cad7d53fab8eab228752d25e3e79f2da9` matches accepted source; CI34484312535 succeeded.
