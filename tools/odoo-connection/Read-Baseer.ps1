#Requires -Version 5.1
param(
    [string]$Model = 'res.users',
    [ValidateSet('context_get','fields_get','search_read','search_count','read')][string]$Method = 'context_get',
    [string[]]$Fields = @(), [string]$DomainJson = '[]', [int[]]$Ids = @(),
    [ValidateRange(1,100)][int]$Limit = 100,
    [ValidateRange(0,2147483647)][int]$Offset = 0, [int[]]$CompanyIds = @(), [switch]$Status
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Baseer.Connection.psm1') -Force
try {
    if ($Status) { Get-BaseerConnectionInfo | ConvertTo-Json; exit 0 }
    if ($DomainJson.Length -gt 32768 -or -not $DomainJson.TrimStart().StartsWith('[')) { throw 'Invalid domain JSON.' }
    $domain = (ConvertFrom-Json -InputObject ('{"domain":' + $DomainJson + '}')).domain
    $request = New-BaseerReadRequest -Model $Model -Method $Method -Fields $Fields -Domain @($domain) -Ids $Ids -Limit $Limit -Offset $Offset -CompanyIds $CompanyIds
    Invoke-BaseerRead -Request $request
} catch {
    # Do not emit error records, invocation details or upstream response bodies.
    [Console]::Error.WriteLine('Read failed. Check model/field allowlist, API access and connection status.')
    exit 1
}
