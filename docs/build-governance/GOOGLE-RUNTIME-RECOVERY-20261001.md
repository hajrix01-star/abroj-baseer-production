# GOOGLE-RUNTIME-RECOVERY-20261001

## Decision and scope

User-authorized repair of production Google Business / Google Ads connectivity.
Base: `e9dc1b728828ffbad4b5db24d52a5a438b63e920` (official main).
Classification: ARCHITECTURAL, narrowly scoped operational defect; no new feature,
schema, accounting rule, company access, credential rotation, or Google writer.

Confirmed: four encrypted connections remain active, but all seven required
Google settings are absent from the live Odoo process. Last recorded sync is
2026-09-20. The protected Google env file still exists with root:root:600.
An earlier runtime override supplied it to Odoo, whereas the current protected
deploy wrapper uses the release Compose file alone. This proves the current
configuration omission; the exact first failing deployment is not yet proven.

## Existing map, targeted correction

```text
Git-reviewed wrapper + named server policy
  -> release Compose + fixed Google-only env_file override
  -> Odoo process -> original encrypted connection -> Google read API
root-only original secret file -----^
```

The wrapper generates a fixed temporary Compose supplement, outside immutable
release directories, with only `services.odoo.env_file` for the canonical
protected Google file. Old release, candidate, config validation, upgrade,
and rollback use the same supplement. Release `.env` still resolves against
the corresponding old/candidate release, never the moving `current` symlink.
Google secrets must not enter PostgreSQL, data-init, Git, logs, or browser.
Missing or unsafe secrets when Google modules are installed abort before
stopping Odoo. No arbitrary historical runtime override is trusted.

## Verification and release plan

- Focused regression fixtures: required secret absence, unsafe ownership/mode,
  symlink, successful Google-only environment merge, old/new/rollback parity,
  no-Google compatibility, SQL probe failure, and no secret output.
- Preflight against the current source: read-only DB transaction, decrypt four
  credentials, OAuth refresh and one bounded provider read per connection;
  no Google writes or operational DB mutations.
- Independent alpha delivery review before merge/release.
- Source through reviewed PR only; root bootstrap of the reviewed wrapper
  outside the immutable release, then named approval + deploy GitHub Actions.
- Existing consistent DB/filestore backup, protected-table fingerprints,
  source identity, original-key decryption, HTTP health and provider reads.
- Bounded read sync may update Google reporting snapshots only after recovery;
  no accounting/POS/project changes, no enabling Business reply publishing.

## Acceptance / rollback

GO requires all four original credentials decrypt in the actual Odoo process,
successful provider reads or an explicit external reauthorization blocker,
healthy login, unchanged protected business fingerprints, and evidence that
future deployment and recovery retain the Google environment. A rejected
Google grant must be reported rather than replaced silently.

The existing deploy rollback restores the previous release and, if mutated,
its matching recovery pair; the corrected wrapper retains original Google
configuration in that previous release as well. Keep the previous reviewed
wrapper as a separately hashed root-only bootstrap recovery copy. No secret
or operational record deletion.

## Evidence log

- Diagnosis: current container Compose labels reference the release Compose
  only; original protected Google env file is present and private.
- Provider preflight: temporary Odoo shell with the original protected env,
  explicitly read-only DB transaction. All four original credentials decrypt;
  all four OAuth refresh calls and bounded provider reads returned HTTP 200.
  The first diagnostic helper queried `writer_enabled` on the location rather
  than connection, producing AttributeError after the two successful GBP reads;
  helper corrected for the final actual-runtime probe. No provider failure or
  DB mutation occurred in this preflight.
- Candidate, tests, review and production receipts: pending.
- Focused tests: 11/11 Linux-root stdlib unittest scenarios passed. Two focused
  regression assertions fail on the previous wrapper and pass with this fix.
  Git-normalized Bash syntax and whitespace checks passed. CI now runs these
  tests whenever production operations source changes.
- Actual Docker Compose 2.40.3 config assertions: all 8 original Google keys
  merge into Odoo only; PostgreSQL/data-init receive none. The release database
  environment and absolute config mount remain unchanged. Expanded config and
  secret values were never printed.
- Parent protection: /srv, production root, secrets are root:root:755;
  secrets/google is root:root:700. All checked parent paths are directories,
  not symlinks; the file is root:root:600. Non-root cannot replace the file.
- Capacity: initial available 2,256,532 KiB versus protected deployment
  requirement 2,692,248 KiB (plus source staging). Keep the safety threshold;
  inspect recoverable unused image cache before any service interruption.
- Source: frozen `faff5534d7a9cd0f70fcc5dc303fb9e033b6d6b0`, merged via
  PR128 as `84121624ee4958f5c56617dd372abfa36ddaaa59`. GitHub source-integrity
  run36903624022 passed all 11 focused tests and six changed-source checks.
  Independent review: CONDITIONAL GO with runtime/parent/Compose evidence,
  named two-module policy, protected previous-wrapper recovery copy and final
  actual-process/provider checks as release conditions.
- Capacity remediation: removed only unused cached official PostgreSQL image
  `sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3`.
  No container references it; registry manifest was verified before removal,
  so it is recoverable by digest. No volume, DB, backup or application source
  deleted. Available space became 2,812,884 KiB; deployment still enforces its
  original capacity threshold before stopping Odoo.
- Named release `baseer-2026-10-01-google-runtime-recovery` pins PR128 merged
  source and exactly `baseer_google_business,baseer_google_ads`. No module
  application code changed; upgrade runs existing reviewed source only.
