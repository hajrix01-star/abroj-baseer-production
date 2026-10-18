# BChat mobile policy extension

Optional dependency on `baseer_bchat`, with no changes to the legacy module,
ERP ACLs or operational data. No additional ORM ACLs are granted: the extension
adds fields to existing models and keeps direct-room creation behind private
Python token helpers.

## Contract

All routes use the original individual Odoo session boundary (session UID must
match the non-superuser environment UID), `auth=user`, no CORS, no-store JSON,
and CSRF for writes. POST bodies are form encoded with exactly `csrf_token` and
`payload` (the JSON object).

- `GET /bchat/api/v2/mobile/policy?company_id=N` returns
  `{api_version:2, company_id:N, direct_enabled:boolean, can_manage:boolean}`.
- `POST /bchat/api/v2/mobile/policy` accepts
  `{api_version:2, company_id:N, direct_enabled:boolean}` and returns the same metadata.
- `POST /bchat/api/v2/mobile/direct` accepts
  `{api_version:2, company_id:N, user_id:N, client_uuid:UUIDv4}` and returns
  `{api_version:2, room_id:N, membership_id:N, replayed:boolean}`.
- `GET /bchat/api/v2/mobile/candidates?company_id=N&q=...` returns
  `{api_version:2, users:[{user_id:N,name:string}]}` (maximum 40). The search
  requires existing group-management/create rights, or chat sending plus enabled
  direct conversations. Results are active internal users enabled for chat in
  the allowed company, and expose no login/email/other company metadata.
- Bootstrap adds `mobile_policy` (one metadata object per allowed company) and
  `permissions.mobile_admin`. Room metadata adds `mobile_direct`.

Direct opening is idempotent by the company and ordered user pair; `replayed`
means the existing pair was opened. The request UUID is validated, but in this
revision is not a separately persisted operation receipt. The endpoint never
revives an inactive membership or grants a company based on a request ID.

## Authorization

`res.company.bchat_mobile_direct_enabled` defaults false. System administrators
can manage policy in their allowed companies. They can explicitly assign
`res.users.bchat_mobile_admin`, which permits only the narrow policy operation
in the assigned user's allowed companies. It grants neither company/user edit
ACLs nor message access. Permission edits and permission defaults supplied in
user-creation context are rejected before inherited create for other users.

Direct rooms have `mobile_direct=True` and an immutable, ordered pair. They
remain `is_group=False`; legacy non-group rooms are never reclassified. Both
participants must be active internal users, allowed in the company and enabled
for chat viewing. The caller additionally needs chat sending to open a pair.
Existing group APIs remain unchanged, and marked direct rooms cannot become
groups or acquire additional members.

Disabling direct conversations preserves member history and read receipts but
blocks direct creation, text/media sends, upload grants and upload commits,
including the existing BChat API routes. Normal groups remain writable.

## Lock and verification boundary

Direct open, send and media preflight acquire a company row `FOR SHARE` before
any room write lock. A policy change acquires `FOR UPDATE` and updates that row.
This prevents a toggle from committing in the middle of a checked DM write.
PostgreSQL/Odoo repeatable-read serialization failures must retry the complete
request. Pair uniqueness is a database constraint; a concurrent pair winner
causes a serialization retry rather than an unverified ACK. Existing capacity
locks and membership epochs are retained. There is no room/content lock in the
toggle path, so administrators do not gain content access.

Focused `TransactionCase` and `HttpCase` suites cover defaults, strict payloads,
forged permission writes/defaults, company boundaries, nonmember access,
manager scope, pair reuse, fixed members, legacy compatibility and original API
write denial after disabling DM. Python compilation and XML parsing are source
checks only. Real HTTP/session and concurrent toggle/send tests require an
isolated Odoo/PostgreSQL test runtime; their execution is not claimed here.
