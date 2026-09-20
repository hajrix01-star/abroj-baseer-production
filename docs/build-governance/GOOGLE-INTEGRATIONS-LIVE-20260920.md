# Google integrations — production candidate

## Scope

This candidate introduces only `baseer_google_business` and
`baseer_google_ads` to production.  It does not replace any existing custom
addon, alter accounting/POS/HR data, or enable a Google write endpoint.

## Runtime posture

- Google Ads is read-only by design.
- Google Business starts with `writer_enabled = false`.  Publishing a reply
  additionally requires both production-only environment locks; this release
  does not set either lock.
- OAuth refresh tokens are never committed, copied from QA, or exposed to the
  browser.  A production connection can only be imported by a controlled
  server-side superuser process under the production master key.
- A system owner cannot bypass that importer by forging an RPC context.

## Release and rollback

The release policy permits exactly the two Google modules.  The production
wrapper creates a consistent PostgreSQL and filestore backup before module
installation, verifies protected business-table fingerprints, and restores the
previous release plus that backup pair if installation or smoke checks fail.

## Acceptance limits

The rollout proves module installation, owner visibility, and read-only
operation.  A connection is considered ready only after a server-side
production credential import and one bounded read sync succeed.  If the
legacy token is invalid, the safe outcome is `Needs re-authorization`; no
token is copied across encryption keys.
