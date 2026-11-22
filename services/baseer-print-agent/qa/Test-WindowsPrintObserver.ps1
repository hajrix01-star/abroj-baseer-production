param([Parameter(Mandatory=$true)][string]$AgentDll)
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFrom((Resolve-Path -LiteralPath $AgentDll).Path)
$observer = $assembly.GetType('WindowsPrintObserver', $true)
$flags = [Reflection.BindingFlags]'NonPublic,Static'
$status = $observer.GetMethod('StatusCode', $flags)
$match = $observer.GetMethod('DocumentMatches', $flags)
$passed = 0
$cases = @{
    0 = 'queue_pending'; 1 = 'queue_paused'; 2 = 'queue_error'; 4 = 'queue_deleted'
    16 = 'queue_printing'; 32 = 'printer_offline'; 64 = 'queue_paperout'
    128 = 'queue_reported_complete'; 256 = 'queue_deleted'; 512 = 'queue_error'
    1024 = 'queue_error'; 4096 = 'queue_reported_complete'; 192 = 'queue_paperout'
}
foreach ($pair in $cases.GetEnumerator()) {
    if ($status.Invoke($null, @([uint32]$pair.Key)) -ne $pair.Value) { throw "Wrong queue classification: $($pair.Key)" }
    $passed++
}
$document = 'Baseer-' + [Guid]::NewGuid().ToString('N')
$buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal(256)
try {
    $bytes = [Text.Encoding]::Unicode.GetBytes($document + [char]0)
    [Runtime.InteropServices.Marshal]::Copy($bytes, 0, $buffer, $bytes.Length)
    if (!$match.Invoke($null, @($buffer, $buffer, [uint32]256, $document))) { throw 'Own correlation was not matched' }
    $passed++
    if ($match.Invoke($null, @($buffer, $buffer, [uint32]256, ('Baseer-' + [Guid]::NewGuid().ToString('N'))))) { throw 'Wrong document correlated' }
    $passed++
    if ($match.Invoke($null, @($buffer, $buffer, [uint32]4, $document))) { throw 'Read outside supplied buffer allowed' }
    $passed++
    if ($match.Invoke($null, @([IntPtr]::Zero, $buffer, [uint32]256, $document))) { throw 'Null document pointer accepted' }
    $passed++
} finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer) }
$diagnostics = $assembly.GetType('AgentDiagnostics', $true)
$rootField = $diagnostics.GetField('_testRoot', $flags)
$activeField = $observer.GetField('active', $flags)
$rootField.SetValue($null, (Join-Path ([IO.Path]::GetTempPath()) ('Baseer-Observer-Test-' + [Guid]::NewGuid().ToString('N'))))
try {
    $activeField.SetValue($null, 1)
    $observer.GetMethod('Observe').Invoke($null, @(123, 'unused-test-printer', 'unused-test-document'))
    $events = $diagnostics.GetMethod('ReadRecent').Invoke($null, @())
    if ($events.Count -ne 1 -or $events[0].Code -ne 'queue_unobserved') { throw 'Normal observer overlap was reported as a printer fault' }
    $passed++
} finally {
    $activeField.SetValue($null, 0)
    $rootField.SetValue($null, $null)
}
Write-Output "WINDOWS_OBSERVER_TESTS_PASSED=$passed NO_PRINTER_CALLS=true"
