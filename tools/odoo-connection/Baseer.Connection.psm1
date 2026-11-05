Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.Security
if (-not ('BaseerLocal.CredentialStore' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'CredentialStore.cs') }
$script:Origin = 'https://baseer.abroj.sa'
$script:CredentialTarget = 'BaseerCodex/Odoo/baseer.abroj.sa'
$script:AllowedFields = @{
    'res.company' = @('id','name','active','currency_id')
    'hr.employee' = @('id','name','active','company_id','version_id','wage','contract_date_start','contract_date_end','baseer_payroll_enabled','baseer_salary_total','baseer_salary_warning','write_date')
    'hr.version' = @('id','name','employee_id','company_id','date_version','contract_date_start','contract_date_end','wage','resource_calendar_id','baseer_salary_mode','baseer_work_days','write_date')
    'hr.payslip' = @('id','name','employee_id','company_id','payslip_run_id','version_id','date_from','date_to','state','baseer_managed','baseer_gross','baseer_net','baseer_days','baseer_month_days','baseer_needs_refresh','baseer_readiness','baseer_readiness_warning','write_date')
    'hr.payslip.run' = @('id','name','company_id','date_start','date_end','state','baseer_month','write_date')
}

function Get-BaseerConnectionInfo {
    $available = $true; $configured = $false
    try { $configured = [BaseerLocal.CredentialStore]::Exists($script:CredentialTarget) } catch { $available = $false }
    [pscustomobject]@{ Origin = $script:Origin; CredentialTarget = $script:CredentialTarget; StorageAvailable = $available; Configured = $configured; Mode = 'read-only'; Models = @($script:AllowedFields.Keys | Sort-Object) }
}

function New-BaseerConnection {
    param([Parameter(Mandatory)][Security.SecureString]$ApiKey, [string]$Database = '')
    if ($ApiKey.Length -lt 16 -or $ApiKey.Length -gt 1024 -or $Database.Length -gt 128 -or $Database -match '[\r\n\x00]') { throw 'Invalid connection input.' }
    [pscustomobject]@{ ApiKey = $ApiKey; Database = $Database.Trim() }
}

function Save-BaseerConnection {
    param([Parameter(Mandatory)]$Connection)
    $pointer = [IntPtr]::Zero
    $bytes = $null
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Connection.ApiKey)
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $document = @{ schema = 1; origin = $script:Origin; database = $Connection.Database; api_key = $plain } | ConvertTo-Json -Compress
        $bytes = [Text.Encoding]::UTF8.GetBytes($document)
        [BaseerLocal.CredentialStore]::Save($script:CredentialTarget, $bytes)
    } catch { throw 'Could not securely save connection; previous connection was retained.' }
    finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        if ($null -ne $bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
        $plain = $null; $document = $null
    }
}

function Get-BaseerConnection {
    $bytes = $null
    $document = $null
    try {
        $bytes = [BaseerLocal.CredentialStore]::Read($script:CredentialTarget)
        $document = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
        if ($document.schema -ne 1 -or $document.origin -cne $script:Origin) { throw 'Invalid store.' }
        $secret = ConvertTo-SecureString -String $document.api_key -AsPlainText -Force
        New-BaseerConnection -ApiKey $secret -Database $document.database
    } catch { throw 'Connection is missing or cannot be decrypted by this Windows user. Run Connect-Baseer.ps1.' }
    finally { if ($null -ne $bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }; $document = $null }
}

function New-BaseerReadRequest {
    param(
        [Parameter(Mandatory)][string]$Model,
        [Parameter(Mandatory)][ValidateSet('context_get','fields_get','search_read','search_count','read')][string]$Method,
        [string[]]$Fields = @(), [object[]]$Domain = @(), [int[]]$Ids = @(),
        [ValidateRange(1,100)][int]$Limit = 100, [ValidateRange(0,2147483647)][int]$Offset = 0,
        [int[]]$CompanyIds = @()
    )
    if ($Method -eq 'context_get') {
        if ($Model -cne 'res.users' -or $Fields.Count -or $Domain.Count -or $Ids.Count -or $CompanyIds.Count) { throw 'Unsupported identity request.' }
        return @{ Model = $Model; Method = $Method; Body = @{} }
    }
    if ($script:AllowedFields.Keys -cnotcontains $Model) { throw 'Model is not enabled for this read-only connection.' }
    if ($Fields.Count -eq 0) { throw 'An explicit field list is required.' }
    foreach ($field in $Fields) { if ($script:AllowedFields[$Model] -cnotcontains $field) { throw 'Field is not enabled for this read-only connection.' } }
    foreach ($id in @($Ids) + @($CompanyIds)) { if ($id -le 0) { throw 'IDs must be positive integers.' } }
    if ($Ids.Count -gt 100) { throw 'At most 100 record IDs are allowed.' }
    foreach ($term in $Domain) {
        if ($term -is [string] -and @('&','|','!') -ccontains $term) { continue }
        if ($term -isnot [array] -or $term.Count -ne 3 -or $script:AllowedFields[$Model] -cnotcontains $term[0]) { throw 'Domain must use enabled fields only.' }
        if (@('=','!=','>','>=','<','<=','in','not in','ilike','=ilike') -cnotcontains $term[1]) { throw 'Unsupported domain operator.' }
        if (($term | ConvertTo-Json -Depth 8 -Compress).Length -gt 8192) { throw 'Domain value is too large.' }
    }
    if ($Domain.Count -gt 40) { throw 'Domain has too many terms.' }
    $body = @{}
    switch ($Method) {
        'fields_get' { $body.allfields = $Fields; $body.attributes = @('string','type','readonly','required') }
        'read' { if ($Ids.Count -eq 0) { throw 'Record IDs are required.' }; $body.ids = $Ids; $body.fields = $Fields }
        'search_read' { $body.domain = @($Domain); $body.fields = $Fields; $body.limit = $Limit; $body.offset = $Offset; $body.order = 'id' }
        'search_count' { $body.domain = @($Domain) }
    }
    if ($CompanyIds.Count) { $body.context = @{ allowed_company_ids = @($CompanyIds) } }
    @{ Model = $Model; Method = $Method; Body = $body }
}

function Read-BaseerResponse {
    param([Parameter(Mandatory)][Net.Http.HttpResponseMessage]$Response, [Parameter(Mandatory)][Threading.CancellationToken]$Token)
    $status = [int]$Response.StatusCode
    if ($status -ge 300 -and $status -lt 400) { throw 'Odoo redirected the request. No redirect was followed.' }
    if ($status -eq 401 -or $status -eq 403) { throw 'Odoo refused this key or its permissions.' }
    if ($status -lt 200 -or $status -ge 300) { throw ('Odoo request failed (HTTP ' + $status + ').') }
    if ($Response.Content.Headers.ContentLength -gt 2097152) { throw 'Odoo response exceeds the 2 MiB limit.' }
    $stream = $null; $memory = New-Object IO.MemoryStream
    try {
        $stream = $Response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $buffer = New-Object byte[] 8192
        while (($count = $stream.ReadAsync($buffer, 0, $buffer.Length, $Token).GetAwaiter().GetResult()) -gt 0) {
            if ($memory.Length + $count -gt 2097152) { throw 'Odoo response exceeds the 2 MiB limit.' }
            $memory.Write($buffer, 0, $count)
        }
        $result = [Text.Encoding]::UTF8.GetString($memory.ToArray())
        try { $null = ConvertFrom-Json -InputObject $result -ErrorAction Stop } catch { throw 'Odoo returned an invalid JSON response.' }
        return $result
    } finally { if ($null -ne $stream) { $stream.Dispose() }; $memory.Dispose() }
}

function Invoke-BaseerRead {
    param([Parameter(Mandatory)][hashtable]$Request, $Connection = (Get-BaseerConnection))
    # Revalidate even a caller-supplied request; only the builder's allowed bodies pass.
    $model = [string]$Request.Model; $method = [string]$Request.Method; $body = $Request.Body
    if ($body -isnot [hashtable]) { throw 'Invalid request body.' }
    $allowedKeys = @('ids','fields','allfields','attributes','domain','limit','offset','order','context')
    foreach ($key in $body.Keys) { if ($allowedKeys -cnotcontains $key) { throw 'Unsupported request body.' } }
    $companies = @()
    if ($body.ContainsKey('context')) {
        if ($body.context -isnot [hashtable] -or $body.context.Count -ne 1 -or -not $body.context.ContainsKey('allowed_company_ids')) { throw 'Unsupported context.' }
        $companies = @($body.context.allowed_company_ids)
    }
    $args = @{ Model = $model; Method = $method; CompanyIds = $companies }
    if ($body.ContainsKey('fields')) { $args.Fields = @($body.fields) }
    if ($body.ContainsKey('allfields')) { $args.Fields = @($body.allfields) }
    if ($body.ContainsKey('domain')) { $args.Domain = @($body.domain) }
    if ($body.ContainsKey('ids')) { $args.Ids = @($body.ids) }
    if ($body.ContainsKey('limit')) { $args.Limit = $body.limit }
    if ($body.ContainsKey('offset')) { $args.Offset = $body.offset }
    $validated = New-BaseerReadRequest @args
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(15)
    $cancellation = New-Object Threading.CancellationTokenSource
    $cancellation.CancelAfter(15000)
    $message = New-Object Net.Http.HttpRequestMessage([Net.Http.HttpMethod]::Post, ($script:Origin + '/json/2/' + $validated.Model + '/' + $validated.Method))
    $response = $null
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Connection.ApiKey)
        $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $message.Headers.Authorization = New-Object Net.Http.Headers.AuthenticationHeaderValue('Bearer', $key)
        if ($Connection.Database) { [void]$message.Headers.TryAddWithoutValidation('X-Odoo-Database', $Connection.Database) }
        $message.Content = New-Object Net.Http.StringContent(($validated.Body | ConvertTo-Json -Depth 12 -Compress), [Text.Encoding]::UTF8, 'application/json')
        $response = $client.SendAsync($message, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $cancellation.Token).GetAwaiter().GetResult()
        return Read-BaseerResponse -Response $response -Token $cancellation.Token
    } catch {
        $safe = @('Odoo redirected the request. No redirect was followed.','Odoo refused this key or its permissions.','Odoo response exceeds the 2 MiB limit.','Odoo returned an invalid JSON response.')
        if ($safe -contains $_.Exception.Message -or $_.Exception.Message -match '^Odoo request failed \(HTTP [0-9]{3}\)\.$') { throw $_.Exception.Message }
        throw 'Cannot reach Odoo securely within 15 seconds. Connection was not changed.'
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        $key = $null
        if ($null -ne $response) { $response.Dispose() }
        $message.Dispose(); $client.Dispose(); $handler.Dispose(); $cancellation.Dispose()
    }
}

Export-ModuleMember -Function Get-BaseerConnectionInfo,New-BaseerConnection,Save-BaseerConnection,Get-BaseerConnection,New-BaseerReadRequest,Invoke-BaseerRead
