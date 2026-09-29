$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$releaseDir = Join-Path $repoRoot '.local-backups/releases/2026-09-07-reports-r1'
if (Test-Path -LiteralPath $releaseDir) { throw 'Release directory already exists. Refusing to overwrite a frozen candidate.' }
New-Item -ItemType Directory -Path $releaseDir | Out-Null
$payloadDir = Join-Path $releaseDir 'payload'
New-Item -ItemType Directory -Path $payloadDir | Out-Null
$modulePaths = @('third_party_addons/erp_heritage_19/eh_account_base','third_party_addons/erp_heritage_19/eh_account_dynamic_reports','custom_addons/baseer_report_layout','custom_addons/baseer_cash_categories')
$entries = @()
foreach ($module in $modulePaths) {
    foreach ($source in Get-ChildItem -LiteralPath (Join-Path $repoRoot $module) -File -Recurse) {
        if ($source.FullName -match '[\\/](__pycache__|\.git)[\\/]' -or $source.Extension -in @('.pyc','.pyo','.log')) { continue }
        $relative = [IO.Path]::GetRelativePath($repoRoot, $source.FullName).Replace('\','/')
        $dest = Join-Path $payloadDir $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
        Copy-Item -LiteralPath $source.FullName -Destination $dest
        $hash = (Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) { throw "Copy mismatch: $relative" }
        $entries += [ordered]@{path=$relative;bytes=$source.Length;sha256=$hash}
    }
}
$prior = Get-Content -LiteralPath (Join-Path $repoRoot 'docs/build-governance/cash_mobile_table_hashes.json') -Raw | ConvertFrom-Json
foreach ($property in $prior.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $repoRoot $property.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) { throw "QA candidate changed: $($property.Name)" }
}
$manifest = [ordered]@{release='baseer-reports-r1';date='2026-09-07';identity='SHA256 source manifest; no Git release commit';scope='Frozen report modules; not deployed to main';modules=@{eh_account_base='19.0.1.8.0';eh_account_dynamic_reports='19.0.1.8.1';baseer_report_layout='19.0.1.1.0';baseer_cash_categories='19.0.1.3.0'};files=@($entries | Sort-Object path)}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Encoding utf8
$services = @()
foreach ($name in @('baseer_odoo_dev-odoo-1','baseer_odoo_dev-reports_qa-1','baseer_odoo_dev-db-1')) {
    $imageId = docker inspect --format '{{.Image}}' $name
    if ($LASTEXITCODE -ne 0) { throw "Inspect failed: $name" }
    $digests = docker image inspect --format '{{json .RepoDigests}}' $imageId
    $services += [ordered]@{container=$name;image_id=$imageId;repo_digests=($digests | ConvertFrom-Json)}
}
$odooVersion = docker compose exec -T odoo odoo --version
if ($LASTEXITCODE -ne 0) { throw 'Runtime version failed' }
$runtime = [ordered]@{checked_at=(Get-Date).ToString('o');odoo_version=$odooVersion;services=$services}
$runtime | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime.json') -Encoding utf8
$states = @()
foreach ($database in @('baseer_dev','baseer_reports_qa_20260907')) {
    $sql = "SELECT json_build_object('database',current_database(),'companies',(SELECT json_agg(json_build_object('id',id,'name',name)) FROM res_company),'account_moves',(SELECT count(*) FROM account_move),'modules',(SELECT json_agg(json_build_object('name',name,'state',state,'version',latest_version)) FROM ir_module_module WHERE name IN ('eh_account_base','eh_account_dynamic_reports','baseer_report_layout','baseer_cash_categories','baseer_core')));"
    $result = docker compose exec -T db psql -U odoo -d $database -X -A -t -c $sql
    if ($LASTEXITCODE -ne 0) { throw "Read-only snapshot failed: $database" }
    $states += $result | ConvertFrom-Json
}
$states | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'database-state.json') -Encoding utf8
$evidenceDir = Join-Path $payloadDir 'evidence'
New-Item -ItemType Directory -Path $evidenceDir | Out-Null
foreach ($file in @('ERP-HERITAGE-EVALUATION.md','CASH-CATEGORIES-REVIEW.md','CASH-COMPACT-REVIEW.md','CASH-MONTHLY-REVIEW.md','CASH-MOBILE-TABLE-REVIEW.md','cash_mobile_table_hashes.json','cash_mobile_table_checks.json','cash_monthly_checks.json','cash_monthly_edge_checks.json','cash_monthly_export_checks.json','cash_monthly_file_checks.json')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "docs/build-governance/$file") -Destination $evidenceDir
}
foreach ($file in @('README.md','TRANSFER.md','NEXT-PURCHASE-BATCH.md','manifest.json','runtime.json')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $payloadDir
}
$archive = Join-Path $releaseDir 'baseer-reports-r1.zip'
Compress-Archive -Path (Join-Path $payloadDir '*') -DestinationPath $archive -CompressionLevel Optimal
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    foreach ($entry in $entries) {
        $item = $zip.GetEntry($entry.path)
        if (-not $item) { $item = $zip.Entries | Where-Object { $_.FullName.Replace('\','/') -eq $entry.path } | Select-Object -First 1 }
        if (-not $item) { throw "Archive missing: $($entry.path)" }
        $stream=$item.Open()
        try { $digest=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() } finally { $stream.Dispose() }
        if ($digest -ne $entry.sha256) { throw "Archive mismatch: $($entry.path)" }
    }
    $zipCount=$zip.Entries.Count
} finally { $zip.Dispose() }
$artifact = [ordered]@{release='baseer-reports-r1';archive=$archive;sha256=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant();bytes=(Get-Item -LiteralPath $archive).Length;source_file_count=$entries.Count;archive_entries=$zipCount;source_and_archive_verified=$true;qa_cash_manifest_matches=$true;main_deployed=$false}
$artifact | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'ARTIFACT.json') -Encoding utf8
$artifact | ConvertTo-Json
