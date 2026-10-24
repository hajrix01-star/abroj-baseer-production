param([string]$Tags = 'reports_unified_export,operations_owner_report,operations_owner_details', [switch]$Browser, [switch]$AllReports)
$ErrorActionPreference = 'Stop'
if ($Tags -match '\s' -or $Tags.Split(',') -contains '') {
    throw 'Test selectors must be non-empty comma-separated values without whitespace.'
}
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskDb = 'baseer-operations-fix-db-20261022'
$metadata = (& docker inspect $taskDb | ConvertFrom-Json)[0]
if ($LASTEXITCODE -ne 0 -or $metadata.Config.Labels.'codex.scope' -ne 'private-isolated' -or
    $metadata.Config.Labels.'codex.task' -ne 'operations-report-fix-20261022' -or
    $metadata.HostConfig.NetworkMode -ne 'none' -or $metadata.HostConfig.PortBindings.PSObject.Properties.Count -gt 0 -or
    $metadata.State.Status -ne 'running') { throw 'Isolated database identity guard failed.' }
$oldPassword = $env:PASSWORD
$taskImage = if ($Browser) { 'sha256:e6fafb834c2a186c5d4bef025bd62919e621d2bf13ccbed285754d4e49678dd3' } else { 'odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd' }
$evidence = Join-Path $taskRoot 'output/reports-unified-engine-20261024'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
try {
    # Ephemeral app containers do not retain their generated filestore assets.
    # Only disposable synthetic-test asset cache is reset; no source documents.
    if ($Browser) {
        & docker exec $taskDb psql -U odoo -d operations_contract -v ON_ERROR_STOP=1 -c "DELETE FROM ir_attachment WHERE url LIKE '/web/assets/%';"
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic asset-cache reset failed.' }
    }
    $env:PASSWORD = (& docker exec $taskDb printenv POSTGRES_PASSWORD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $env:PASSWORD) { throw 'Test database credential unavailable.' }
    $modules = @('baseer_reports_menu', 'baseer_operations_report')
    if ($AllReports) {
        $modules += @('baseer_account_activity', 'baseer_general_ledger_report', 'baseer_trial_balance_report',
            'baseer_balance_sheet_report', 'baseer_profit_loss_report', 'baseer_aged_receivable_report',
            'baseer_aged_payable_report', 'baseer_tax_report', 'baseer_pos_tobacco_report')
    }
    if ($Browser) { $modules = @('web') + $modules }
    $upgrade = $modules -join ','
    # Names are the fixed list above, never user-provided SQL or module selectors.
    $quotedModules = ($modules | ForEach-Object { "'$_'" }) -join ','
    $missing = @(& docker exec $taskDb psql -U odoo -d operations_contract -At -v ON_ERROR_STOP=1 -c "SELECT name FROM ir_module_module WHERE state = 'uninstalled' AND name IN ($quotedModules) ORDER BY name;")
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic module inventory failed.' }
    $initialization = @()
    if ($missing.Count -gt 0) { $initialization = @('-i', ($missing -join ',')) }
    & docker run --rm --network "container:$taskDb" --memory 2g --cpus 2 `
        -e HOST=127.0.0.1 -e USER=odoo -e PASSWORD `
        -e BASEER_EXPORT_EVIDENCE_DIR=/mnt/evidence `
        --mount "type=bind,source=$evidence,target=/mnt/evidence" `
        --mount "type=bind,source=$taskRoot/custom_addons,target=/mnt/baseer-addons,readonly" `
        --mount "type=bind,source=$taskRoot/third_party_addons,target=/mnt/third-party-addons,readonly" `
        $taskImage `
        odoo --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/oca_dms_19,/mnt/third-party-addons/odoomates_19 `
        -d operations_contract -u $upgrade @initialization --without-demo=all `
        --http-interface=127.0.0.1 --test-enable "--test-tags=$Tags" --stop-after-init --max-cron-threads=0 --workers=0 --log-level=test
    if ($LASTEXITCODE -ne 0) { throw "Odoo tests failed ($LASTEXITCODE)." }
} finally {
    $env:PASSWORD = $oldPassword
}
