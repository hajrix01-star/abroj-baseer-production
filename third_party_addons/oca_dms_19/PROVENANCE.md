# OCA DMS 19 — QA evaluation

Repository: https://github.com/OCA/dms
Revision: 1a3098d1d6bbce6a38d06d9f361db319e7858fa3 (19.0)
Module: dms 19.0.1.1.2, LGPL-3 per module manifest; retain per-file notices.
Runtime source is that revision with a local destination-access fix in
dms/models/dms_security_mixin.py: relocation checks destination read/create
and storage company rules without elevating the actor, then rechecks resulting
record permissions inside a rollback savepoint. Internal sudo behavior and
native cross-storage directory restrictions are unchanged. The strict native
cross-company move regression is included in CI, not waived. Arabic error
translations for this patch are added in dms/i18n/ar.po.
README.rst has only
two repository-check formatting corrections: remove a trailing space and use
an asterisk Credits heading underline instead of a conflict-marker-like line.
No other OCA addons
are included. Initial scope is QA synthetic contracts/licenses, not production.
Native duplicate-content prevention is NOT provided. Shared storage, public
tokens and automatic attachment integration are not enabled in trial fixtures.
