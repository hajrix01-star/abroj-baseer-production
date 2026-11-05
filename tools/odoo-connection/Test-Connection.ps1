#Requires -Version 5.1
param([switch]$NativeStore)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$module = Import-Module (Join-Path $PSScriptRoot 'Baseer.Connection.psm1') -Force -PassThru
$script:Checks = 0
function Assert([bool]$Condition, [string]$Name) { if (-not $Condition) { throw ('FAIL: ' + $Name) }; $script:Checks++ }
function Reject([scriptblock]$Action, [string]$Name) { $rejected = $false; try { & $Action | Out-Null } catch { $rejected = $true }; Assert $rejected $Name }

foreach ($file in Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object Extension -in '.ps1','.psm1') {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    Assert ($errors.Count -eq 0) ('parse ' + $file.Name)
}
Assert ((Get-BaseerConnectionInfo).Origin -ceq 'https://baseer.abroj.sa') 'pinned origin'
Reject { New-BaseerReadRequest -Model res.users -Method search_read -Fields id } 'security model denied'
Reject { New-BaseerReadRequest -Model hr.employee -Method write -Fields id } 'write denied'
Reject { New-BaseerReadRequest -Model hr.employee -Method search_read } 'implicit fields denied'
Reject { New-BaseerReadRequest -Model hr.employee -Method search_read -Fields id,password } 'secret field denied'
Reject { New-BaseerReadRequest -Model hr.employee -Method search_read -Fields id -Limit 101 } 'page cap'
Reject { New-BaseerReadRequest -Model hr.employee -Method read -Fields id -Ids (1..101) } 'read cap'
Reject { New-BaseerReadRequest -Model hr.employee -Method search_read -Fields id -CompanyIds -1 } 'negative company'
Reject { New-BaseerReadRequest -Model Hr.Employee -Method search_read -Fields id } 'model casing exact'
Reject { New-BaseerReadRequest -Model hr.employee -Method search_read -Fields id -Domain @(@('password','=',$true), @('id','=',1)) } 'domain field denied'
$request = New-BaseerReadRequest -Model hr.employee -Method search_read -Fields id,name -CompanyIds 1
Assert ($request.Body.limit -eq 100 -and $request.Body.context.allowed_company_ids[0] -eq 1) 'bounded company request'
foreach ($json in @('[]','[["active","=",true]]','[["active","=",true],["company_id","=",1]]','["|",["id","=",1],["id","=",2]]')) {
    $domain = (ConvertFrom-Json -InputObject ('{"domain":' + $json + '}')).domain
    $request = New-BaseerReadRequest -Model hr.employee -Method search_read -Fields id,name -Domain @($domain)
    Assert ($request.Body.domain.Count -eq @($domain).Count) 'JSON domain shape preserved'
}
$request = New-BaseerReadRequest -Model hr.employee -Method fields_get -Fields id,name
Assert ($request.Body.allfields.Count -eq 2 -and $request.Body.attributes.Count -eq 4) 'schema fields bounded'
$context = New-BaseerReadRequest -Model res.users -Method context_get
Assert ($context.Body.Count -eq 0) 'identity request empty'
Reject { Invoke-BaseerRead -Request @{Model='res.users';Method='context_get';Body=@{context=@{sudo=$true}}} -Connection @{} } 'forged context rejected before transport'
Reject { Invoke-BaseerRead -Request @{Model='hr.employee';Method='write';Body=@{}} -Connection @{} } 'forged method rejected before transport'

# All native-store checks use a unique TEST target, never the real credential.
if ($NativeStore) {
$testTarget = 'BaseerCodex/TEST/' + [Guid]::NewGuid().ToString('N')
& $module { param($Target) $script:CredentialTarget = $Target } $testTarget
try {
$fake = 'TEST-ONLY-NOT-AN-ODOO-KEY-123456789'
$connection = New-BaseerConnection -ApiKey (ConvertTo-SecureString $fake -AsPlainText -Force) -Database 'test_database'
Save-BaseerConnection -Connection $connection
$stored = Get-BaseerConnection
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($stored.ApiKey)
try { Assert ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) -ceq $fake) 'native credential roundtrip' }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $stored.ApiKey.Dispose() }
Assert ((Get-BaseerConnectionInfo).Configured) 'credential exists'
Assert (-not (Get-BaseerConnectionInfo | ConvertTo-Json).Contains($fake)) 'status contains no secret'
Reject { New-BaseerConnection -ApiKey (ConvertTo-SecureString 'short' -AsPlainText -Force) } 'invalid key denied'
$unchanged = Get-BaseerConnection
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($unchanged.ApiKey)
try { Assert ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) -ceq $fake) 'prior credential preserved' }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $unchanged.ApiKey.Dispose() }
$second = New-BaseerConnection -ApiKey (ConvertTo-SecureString 'TEST-ONLY-SECOND-NOT-ODOO-KEY-123' -AsPlainText -Force)
Save-BaseerConnection -Connection $second
$replaced = Get-BaseerConnection
Assert ($replaced.Database -ceq '') 'credential replacement'
$replaced.ApiKey.Dispose()
$connection.ApiKey.Dispose(); $second.ApiKey.Dispose()
} finally { [BaseerLocal.CredentialStore]::DeleteTest($testTarget) }
Assert (-not [BaseerLocal.CredentialStore]::Exists($testTarget)) 'fake credential removed'
Reject { [BaseerLocal.CredentialStore]::DeleteTest('BaseerCodex/Odoo/baseer.abroj.sa') } 'production credential protected from test deletion'
}

foreach ($status in @(302,401,403,502)) {
    $response = New-Object Net.Http.HttpResponseMessage([Net.HttpStatusCode]$status)
    $response.Content = New-Object Net.Http.StringContent('MUST-NOT-LEAK')
    try {
        $errorMessage = ''
        try { & $module { param($r) Read-BaseerResponse $r ([Threading.CancellationToken]::None) } $response | Out-Null } catch { $errorMessage = $_.Exception.Message }
        Assert ($errorMessage.Length -gt 0 -and -not $errorMessage.Contains('MUST-NOT-LEAK')) ('sanitize HTTP ' + $status)
    } finally { $response.Dispose() }
}
$response = New-Object Net.Http.HttpResponseMessage([Net.HttpStatusCode]::OK)
$response.Content = New-Object Net.Http.StringContent(('x' * 2097153))
try { Reject { & $module { param($r) Read-BaseerResponse $r ([Threading.CancellationToken]::None) } $response } 'response size cap' } finally { $response.Dispose() }
$response = New-Object Net.Http.HttpResponseMessage([Net.HttpStatusCode]::OK)
$response.Content = New-Object Net.Http.StringContent('{"uid":42,"allowed_company_ids":[1]}')
try { $text = & $module { param($r) Read-BaseerResponse $r ([Threading.CancellationToken]::None) } $response; Assert (($text | ConvertFrom-Json).uid -eq 42) 'valid response' } finally { $response.Dispose() }
Write-Output ('PASS: ' + $script:Checks + ' offline checks; no network calls or real credentials. NativeStore=' + [bool]$NativeStore)
