# Heat Calendar Isolated Demo Runbook

## Scope and invariants

- Candidate code only: `heat_calendar_demo_source` at its recorded commit.
- Read-only source database: `baseer_integrated_release_candidate_20260914`.
- New clone only: `baseer_heat_calendar_demo_20260914`.
- The demo does not run scheduled jobs and listens only at `127.0.0.1:18087`.
- It never writes to `baseer_dev`, `baseer_prod`, the integrated release candidate, or any production database.

## Preconditions

1. Docker Desktop is healthy: `docker version` must show both client and server.
2. Confirm that the candidate worktree commit matches the delivery receipt.
3. Confirm the read-only source database exists, has no remaining client sessions when cloning begins, and obtain a current logical backup with a SHA-256 receipt before cloning.
4. Start the local database only if it is not already healthy. Do not restart or recreate it solely for this demo.

## Controlled execution

All commands below use the root compose file plus `compose.heat-calendar-demo.yaml`; the latter is not a standalone stack. This ensures the demo joins only the existing local database network and waits for its health check.

1. Create the clone through the local PostgreSQL service. First verify the target database does not exist. Create it from the named source only after the verification.
2. Start a one-off update against only `baseer_heat_calendar_demo_20260914` with `--stop-after-init -i baseer_sales_heat_calendar --without-demo=True --max-cron-threads=0` and the explicit approved add-on paths.
3. Check invariants before HTTP starts: source model counts are unchanged; the new database is the only database receiving the new module; no data was written to `account.move`, HR, `calendar.event`, `resource.calendar`, or any sales summary model.
4. Start `heat_calendar_demo` using the same two compose files and expose only loopback port 18087.
5. Run the functional, security, Arabic/English, narrow-screen, favourite, and warm-load checks defined in the delivery review. Record actual timings rather than claiming the target.

### Repeatable PowerShell sequence

Run from the repository root only after the preconditions have passed. These are intentionally literal names, rather than a selector or wildcard.

```powershell
$ErrorActionPreference = 'Stop'
$project = 'baseer_odoo_dev'
$expectedDbContainer = 'baseer_odoo_dev-db-1'
$expectedPostgresVolume = 'baseer_odoo_dev_postgres-data'
$files = @('-f', 'compose.yaml', '-f', 'compose.heat-calendar-demo.yaml')
$sourceDb = 'baseer_integrated_release_candidate_20260914'
$demoDb = 'baseer_heat_calendar_demo_20260914'
$candidate = 'release_candidates/2026-09-14-abroj-baseer/heat_calendar_demo_source'
$requiredCommit = '90e5e0f15c8302c6cc4296892638570a5a3ed7d5'
$evidence = 'release_candidates/2026-09-14-abroj-baseer/runtime_evidence/heat-calendar-demo'

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DockerArgs)
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed ($LASTEXITCODE): docker $($DockerArgs -join ' ')" }
}

Invoke-Docker version
$actualCommit = (git -C $candidate rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not read candidate commit.' }
if ($actualCommit -ne $requiredCommit) { throw 'Candidate commit does not match the receipt.' }
if (git -C $candidate status --porcelain) { throw 'Candidate worktree is not clean.' }
if ($LASTEXITCODE -ne 0) { throw 'Could not read candidate worktree status.' }
$actualProject = (Invoke-Docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' $expectedDbContainer).Trim()
$actualService = (Invoke-Docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' $expectedDbContainer).Trim()
$actualVolume = (Invoke-Docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' $expectedDbContainer).Trim()
if ($actualProject -ne $project -or $actualService -ne 'db' -or $actualVolume -ne $expectedPostgresVolume) { throw 'Existing PostgreSQL container or data volume does not match the approved local environment.' }
if ((Invoke-Docker inspect --format '{{.State.Running}}' $expectedDbContainer).Trim() -ne 'true') { Invoke-Docker start $expectedDbContainer }
Invoke-Docker compose --project-name $project @files exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

$exists = Invoke-Docker compose --project-name $project @files exec -T -e "CHECK_SQL=SELECT 1 FROM pg_database WHERE datname = '$demoDb'" db sh -lc 'psql -U "$POSTGRES_USER" -d postgres -Atqc "$CHECK_SQL"'
if ($exists.Trim() -eq '1') { throw "Refusing to reuse existing demo database: $demoDb" }
$sourceExists = Invoke-Docker compose --project-name $project @files exec -T -e "CHECK_SQL=SELECT 1 FROM pg_database WHERE datname = '$sourceDb'" db sh -lc 'psql -U "$POSTGRES_USER" -d postgres -Atqc "$CHECK_SQL"'
if ($sourceExists.Trim() -ne '1') { throw "Required read-only source database is missing: $sourceDb" }
$sourceConnectionSql = "SELECT count(*) FROM pg_stat_activity WHERE datname = '$sourceDb' AND pid <> pg_backend_pid()"
$sourceConnections = Invoke-Docker compose --project-name $project @files exec -T -e "CHECK_SQL=$sourceConnectionSql" db sh -lc 'psql -U "$POSTGRES_USER" -d postgres -Atqc "$CHECK_SQL"'
if ([int]$sourceConnections.Trim() -ne 0) { throw "Refusing to clone a source database with active sessions: $sourceDb" }

New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$countSql = 'SELECT ''account_move'', count(*) FROM account_move UNION ALL SELECT ''hr_payslip'', count(*) FROM hr_payslip UNION ALL SELECT ''calendar_event'', count(*) FROM calendar_event UNION ALL SELECT ''resource_calendar'', count(*) FROM resource_calendar UNION ALL SELECT ''baseer_pos_summary'', count(*) FROM baseer_pos_summary ORDER BY 1'
$sourceSnapshot = Invoke-Docker compose --project-name $project @files exec -T -e "CHECK_SQL=$countSql" db sh -lc 'psql -U "$POSTGRES_USER" -d baseer_integrated_release_candidate_20260914 -Atqc "$CHECK_SQL"'
$sourceSnapshot | Set-Content -LiteralPath "$evidence\source-counts-before.txt" -NoNewline
$sourceSnapshot | Set-Content -LiteralPath "$evidence\source-counts-expected.txt" -NoNewline

$backupPath = Join-Path $evidence "$sourceDb.before-demo.dump"
$containerDump = '/tmp/heat-calendar-source-before-demo.dump'
Invoke-Docker compose --project-name $project @files exec -T db sh -lc 'rm -f /tmp/heat-calendar-source-before-demo.dump && pg_dump -U "$POSTGRES_USER" -Fc baseer_integrated_release_candidate_20260914 -f /tmp/heat-calendar-source-before-demo.dump'
Invoke-Docker cp "${expectedDbContainer}:$containerDump" $backupPath
Invoke-Docker compose --project-name $project @files exec -T db sh -lc 'rm -f /tmp/heat-calendar-source-before-demo.dump'
if ((Get-Item -LiteralPath $backupPath).Length -eq 0) { throw 'Source backup is empty.' }
(Get-FileHash -Algorithm SHA256 -LiteralPath $backupPath).Hash | Set-Content -LiteralPath "$backupPath.sha256" -NoNewline

Invoke-Docker compose --project-name $project @files exec -T db sh -lc 'createdb -U "$POSTGRES_USER" -T baseer_integrated_release_candidate_20260914 baseer_heat_calendar_demo_20260914'
Invoke-Docker compose --project-name $project @files run --rm --no-deps heat_calendar_demo odoo --config=/etc/odoo/odoo.local.conf --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 --database=$demoDb --db-filter="^$demoDb`$" --no-database-list --max-cron-threads=0 --without-demo=True --stop-after-init -i baseer_sales_heat_calendar
$sourceSnapshotAfter = Invoke-Docker compose --project-name $project @files exec -T -e "CHECK_SQL=$countSql" db sh -lc 'psql -U "$POSTGRES_USER" -d baseer_integrated_release_candidate_20260914 -Atqc "$CHECK_SQL"'
$targetSnapshot = Invoke-Docker compose --project-name $project @files exec -T -e "CHECK_SQL=$countSql" db sh -lc 'psql -U "$POSTGRES_USER" -d baseer_heat_calendar_demo_20260914 -Atqc "$CHECK_SQL"'
$sourceSnapshotAfter | Set-Content -LiteralPath "$evidence\source-counts-after.txt" -NoNewline
$targetSnapshot | Set-Content -LiteralPath "$evidence\target-counts-after-init.txt" -NoNewline
if ($sourceSnapshotAfter -ne $sourceSnapshot) { throw 'Source protected-model counts changed; do not start HTTP.' }
if ($targetSnapshot -ne $sourceSnapshot) { throw 'Target protected-model counts differ after module init; do not start HTTP.' }
Invoke-Docker compose --project-name $project @files up -d --no-deps heat_calendar_demo
```

The final `up` command starts only the demo service. It does not restart the regular local Odoo service. The guarded clone command is the only command in the sequence that creates database state.

### Filestore policy

The cloned database needs its matching asset filestore to render the Odoo web client reliably. Copy **only** `filestore/baseer_integrated_release_candidate_20260914` from the source candidate data volume into `filestore/baseer_heat_calendar_demo_20260914` in the separately named demo data volume. Mount the source volume read-only, verify the destination does not already exist, then verify file count and total bytes match before starting HTTP. Do not copy any other database directory, cache, session, or source volume content; the source volume remains read-only throughout.

## Rollback

Stop and remove `heat_calendar_demo`, then remove only the database named `baseer_heat_calendar_demo_20260914` and the volume `baseer_odoo_dev_heat-calendar-demo-odoo-data`, after re-verifying their exact names. The source candidate and all original databases remain untouched.

## Prohibited shortcuts

- Do not use a database selector, wildcard `db-filter`, `--update=all`, or an unpinned image.
- Do not bind to a non-loopback host interface.
- Do not use source data as the target database.
- Do not remove Docker, PostgreSQL, Odoo, or shared volumes as a recovery step.
