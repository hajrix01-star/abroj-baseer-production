# FA2 → MAIN transfer runbook — not executed

Target: existing `baseer_dev`, MAIN service `odoo` in Compose project `baseer_odoo_dev`, PostgreSQL container `baseer_odoo_dev-db-1`. This document prepares a later authorized maintenance window; it does not transfer the candidate. Keep QA and its database/filestore separate. Never restore a QA or test-clone dump over MAIN.

## 1. Freeze and prerequisites

Use [candidate.json](candidate.json) and `candidate-source.zip`:1089 files; the authoritative ZIP SHA256 is `candidate.archive_sha256`. Verify the archive and every extracted file against `candidate.files`; fail on missing, extra executable source or mismatched files. Use the candidate's immutable `source_directory`, currently `D:\Codex\Baseer-odoo\.local-backups\fa2-20260909\candidate`; never bind a working directory that another agent can edit.

The engine is exactly `candidate.engine`: `odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`. Verify against [engine-proof.json](engine-proof.json). Do not pull a moving Odoo tag or use the different local `odoo/` checkout. Keep the previously accepted MAIN image and source snapshot available for rollback; the current edited workspace is **not** proof of a previous release. Privately retain the actual MAIN Compose configuration, `.env`, Odoo configuration and image ID without publishing secrets.

Confirm the current independent release decision, the successful MAIN-clone install/upgrade and attachment restore evidence still match this candidate. Existing [MAIN projection](main-projection-result.json) proves original financial columns/rows were unchanged on that rehearsal, not on the live target. If MAIN has changed since rehearsal, refresh its clone and repeat acceptance before the transfer. No FA2 fixture, race or mutating test script belongs on MAIN.

## 2. Maintenance and coherent backup

Commands below are PowerShell examples from `D:\Codex\Baseer-odoo`. Treat each nonzero exit code as a stop. Before the window, create a **new**, uniquely named private backup directory; the example name must not already exist. Record live MAIN database identity, installed module versions, image ID, mount paths and active Compose file list. Confirm the service/container names still match the target.

```powershell
$fa2MainBackup = 'D:/Codex/Baseer-odoo/.local-backups/fa2-main-transfer-YYYYMMDD-HHMM'
if (Test-Path -LiteralPath $fa2MainBackup) { throw 'Choose a new backup directory' }
New-Item -ItemType Directory -Path $fa2MainBackup
docker compose -p baseer_odoo_dev -f compose.yaml stop odoo
docker inspect --format '{{.State.Running}}' baseer_odoo_dev-odoo-1
docker inspect --format '{{.Image}}' baseer_odoo_dev-odoo-1
```

Require `Running=false`, prevent other clients from writing `baseer_dev`, and verify zero sessions for that database through `pg_stat_activity`. PostgreSQL stays running. Do not stop shared QA/DB services or use `down -v`. Capture a fresh **pre-upgrade original-column/original-ID baseline** for account moves, move lines, payments, partial/full reconciliations and any existing payroll/POS sources, plus partner/company/employee metadata separately.

```powershell
docker exec baseer_odoo_dev-db-1 sh -c 'pg_dump -U "$POSTGRES_USER" -Fc baseer_dev -f /tmp/fa2-main-transfer-before.dump'
docker cp baseer_odoo_dev-db-1:/tmp/fa2-main-transfer-before.dump "$fa2MainBackup/database.dump"
docker run --rm --volumes-from baseer_odoo_dev-odoo-1:ro `
  --mount "type=bind,source=$fa2MainBackup,target=/backup" `
  --entrypoint tar odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd `
  -czf /backup/filestore.tar.gz -C /var/lib/odoo/filestore baseer_dev
Get-FileHash "$fa2MainBackup/database.dump" -Algorithm SHA256
Get-FileHash "$fa2MainBackup/filestore.tar.gz" -Algorithm SHA256
```

Store the baseline, checksums, **previous verified addon snapshot**, image/configuration and private configuration files with this backup. Restore the dump to a distinct temporary database and extract its filestore into a distinct directory. Verify native attachment `store_fname` existence and content checksum plus financial baseline equality. A dump file existing or `pg_restore --list` succeeding is insufficient. Do not proceed if the matched database/filestore/source/config rollback set cannot be restored.

## 3. Bind the candidate and run the reviewed upgrade

Create a dedicated operator-reviewed `transfer-main.override.yaml` **when executing the authorized window**, with this content. Its three addon mounts override the corresponding MAIN mounts; the image and folders must match `candidate.json`:

```yaml
services:
  odoo:
    image: odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd
    volumes:
      - ./.local-backups/fa2-20260909/candidate/custom_addons:/mnt/baseer-addons:ro
      - ./.local-backups/fa2-20260909/candidate/custom_addons:/mnt/extra-addons:ro
      - ./.local-backups/fa2-20260909/candidate/third_party_addons:/mnt/third-party-addons:ro
```

Use the same module set as `fa2_ops.py upgrade main`: the **11 installed Baseer modules in `modules-before.json` plus `om_hr_payroll`**, both `--init` and `--update`. Odoo resolves their native dependencies, including `om_hr_payroll_account`. Candidate packaging also contains unused modules; do not derive the installation set from every packaged manifest and do not use `-u all` or install the evaluated OpenHRMS modules.

```powershell
$fa2MainModules = 'baseer_cash_categories,baseer_category_display,baseer_company_setup,baseer_hr_services,baseer_legion_compat,baseer_payroll,baseer_pos_summary,baseer_purchase_batch,baseer_report_layout,baseer_service_seed,baseer_web_navigation,om_hr_payroll'
$fa2MainAddons = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19'
docker compose -p baseer_odoo_dev -f compose.yaml -f transfer-main.override.yaml `
  run --rm --no-deps odoo odoo --config=/etc/odoo/odoo.local.conf `
  --database=baseer_dev '--db-filter=^baseer_dev$' --no-database-list `
  "--addons-path=$fa2MainAddons" "--init=$fa2MainModules" "--update=$fa2MainModules" `
  --without-demo=all --stop-after-init --no-http --max-cron-threads=0
```

Retain exit status and a private operator log. `fa2_ops.py` itself targets disposable clones; **do not edit its guards or call it expecting a live transfer**. The command above deliberately names the actual target and requires the maintenance/backup steps first. No user/QA company IDs, passwords or fixture data are copied. Keep MAIN stopped until verification passes.

## 4. Verify, then reopen MAIN

Compare the fresh pre-upgrade baseline on original row IDs and original columns. Require zero changed/deleted pre-existing financial rows and zero unexplained new financial transactions; check account/partner/company, dates, posted state, debit/credit/currency/tax amounts, payment links and reconciliation edges, not merely row counts or net totals. Classify additive schema/seed rows and known source-ownership metadata separately. MASTER `write_date/write_uid` differences must be reviewed explicitly as in [main-metadata-diff.json](main-metadata-diff.json); they do not justify ignoring financial changes.

Verify the11 Baseer modules and OdooMates versions against `candidate.module_versions`, no pending module operations, valid account settings, native report namespace, record rules, source links and readable attachment checksums. Run a **read-only live-target adaptation** of the checks documented in `main-acceptance.py`; that existing script is clone-guarded and must not be run unchanged on MAIN. Use existing records for Arabic desktop/mobile, form navigation, financial source drilldown and native PDF checks; test new financial transactions only in a disposable clone. Archive the results beside the transfer backup.

QA operational observation: POS ownership backfill uses native ORM writes, which mark `is_manually_modified=true`. On QA only four existing **posted journal entries** changed this flag, with no other original business column changes; exact before-image and source ownership were independently verified. This flag affects imported purchase-bill auto-post suggestions, not those entries. Do not exclude it globally or permit it on invoices. If MAIN produces any difference, stop reopening and independently classify each row against the fresh baseline, as in `qa-update-result.json`; never reuse QA IDs or its target-specific `finish-qa.py` on MAIN.

When preservation and acceptance pass, reopen using the **same override**, preserving immutable mounts for future restarts:

```powershell
docker compose -p baseer_odoo_dev -f compose.yaml -f transfer-main.override.yaml up -d --no-deps odoo
```

Confirm the running image, addon paths and database filter, then release the maintenance window. Record deployment time, operator, manifest checksum and the backup/restore evidence. This runbook does not claim those steps have happened.

## 5. Full rollback

If any upgrade or acceptance check fails before users resume, keep MAIN and all MAIN writers stopped. Restore **the entire `baseer_dev` database from this window's dump**, its exact `baseer_dev` filestore, the previous verified addon snapshot, engine image and previous configuration/Compose bindings as one matched set. Recreate only the explicitly verified MAIN database/filestore target; preserve other databases and the shared PostgreSQL/Odoo volumes. Validate restored original row projections, attachments, module state and running bindings before reopening.

No single-table restore, copied payroll/POS rows, addon-file deletion, module uninstall, QA dump substitution or database-only rollback is acceptable. If any new business transactions were admitted after reopening, do not overwrite them with the old snapshot: stop writing, preserve a fresh incident backup and agree a forward repair or complete recovery that accounts for those transactions. Retain both snapshots and the incident record.
