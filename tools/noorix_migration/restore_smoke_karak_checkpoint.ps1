param(
    [string]$Checkpoint = "20260913-karak-financial-prewrite-qa-1",
    [string]$ProofDatabase = "baseer_noorix_karak_restore_proof_20260913"
)

$ErrorActionPreference = "Stop"
$dbContainer = "baseer_odoo_dev-db-1"
$checkpointRoot = Resolve-Path -LiteralPath ".local-backups/noorix-migration/$Checkpoint"
$dumpHost = Join-Path $checkpointRoot "database.dump"
$filestoreHost = Join-Path $checkpointRoot "filestore.tar"
$dumpContainer = "/tmp/$Checkpoint-restore-smoke.dump"
$evidencePath = "docs/operations/2026-09-13-noorix-karak-financial/restore-smoke-evidence.json"
$created = $false

if ($ProofDatabase -notmatch '^[a-z0-9_]+$') {
    throw "Invalid proof database name"
}

$existing = docker exec $dbContainer psql -U odoo -d postgres -At -c "SELECT datname FROM pg_database WHERE datname='$ProofDatabase';"
if ($LASTEXITCODE -ne 0) { throw "Could not inspect PostgreSQL" }
if ($existing -eq $ProofDatabase) { throw "Refusing to overwrite existing database: $ProofDatabase" }

try {
    docker cp $dumpHost "${dbContainer}:$dumpContainer" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not copy dump" }
    docker exec $dbContainer createdb -U odoo $ProofDatabase
    if ($LASTEXITCODE -ne 0) { throw "Could not create proof database" }
    $created = $true
    docker exec $dbContainer pg_restore -U odoo -d $ProofDatabase --no-owner --no-privileges $dumpContainer
    if ($LASTEXITCODE -ne 0) { throw "Restore failed" }

    $counts = docker exec $dbContainer psql -U odoo -d $ProofDatabase -At -F '|' -c "SELECT (SELECT count(*) FROM res_company),(SELECT count(*) FROM res_partner),(SELECT count(*) FROM product_template),(SELECT count(*) FROM account_move),(SELECT count(*) FROM account_payment),(SELECT count(*) FROM stock_move),(SELECT count(*) FROM stock_picking),(SELECT count(*) FROM pos_order),(SELECT count(*) FROM pos_session);"
    if ($LASTEXITCODE -ne 0) { throw "Could not read restored counts" }
    $databaseBytes = docker exec $dbContainer psql -U odoo -d $ProofDatabase -At -c "SELECT pg_database_size(current_database());"
    $tocLines = (docker exec $dbContainer pg_restore --list $dumpContainer | Measure-Object -Line).Lines
    $archiveEntries = @(tar -tf $filestoreHost)
    $expected = "4|352|583|2548|1229|0|0|669|670"

    $evidence = [ordered]@{
        schema = "baseer-restore-smoke-evidence/v1"
        executed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        source_checkpoint = $Checkpoint
        source_database_dump_sha256 = (Get-FileHash -LiteralPath $dumpHost -Algorithm SHA256).Hash.ToLower()
        source_filestore_sha256 = (Get-FileHash -LiteralPath $filestoreHost -Algorithm SHA256).Hash.ToLower()
        temporary_database = $ProofDatabase
        restored_database_bytes = [int64]$databaseBytes
        dump_toc_lines = $tocLines
        restored_columns = @("companies", "partners", "product_templates", "account_moves", "payments", "stock_moves", "stock_pickings", "pos_orders", "pos_sessions")
        restored_values = @($counts.Split('|') | ForEach-Object { [int]$_ })
        expected_values = @($expected.Split('|') | ForEach-Object { [int]$_ })
        counts_match = ($counts -eq $expected)
        filestore_archive_entries = $archiveEntries.Count
        filestore_first_entry = $archiveEntries[0]
        filestore_last_entry = $archiveEntries[-1]
        result = if ($counts -eq $expected) { "RESTORE_OK" } else { "RESTORE_COUNT_MISMATCH" }
        cleanup = "temporary database and copied dump removed after verification"
    }
    $evidence | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $evidencePath -Encoding utf8NoBOM
    if (-not $evidence.counts_match) { throw "Restored counts do not match checkpoint baseline" }
    $evidence | ConvertTo-Json -Depth 5
}
finally {
    if ($created) {
        $resolved = docker exec $dbContainer psql -U odoo -d postgres -At -c "SELECT datname FROM pg_database WHERE datname='$ProofDatabase';"
        if ($resolved -eq $ProofDatabase) {
            docker exec $dbContainer dropdb -U odoo $ProofDatabase
        }
    }
    docker exec $dbContainer rm -f $dumpContainer
}
