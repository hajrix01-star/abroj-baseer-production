param([Parameter(Mandatory=$true)][string]$AgentDll)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.IO.Compression
Add-Type -TypeDefinition @'
using System;
using System.Threading;
public sealed class DiagnosticMutexFixture : IDisposable {
    private readonly Thread thread;
    private readonly ManualResetEvent ready = new ManualResetEvent(false);
    private readonly ManualResetEvent done = new ManualResetEvent(false);
    public DiagnosticMutexFixture(string name) {
        thread = new Thread(() => {
            using (var mutex = new Mutex(false, name)) {
                mutex.WaitOne();
                ready.Set();
                done.WaitOne();
                mutex.ReleaseMutex();
            }
        });
        thread.IsBackground = true;
        thread.Start();
        if (!ready.WaitOne(5000)) throw new Exception("Mutex fixture did not start.");
    }
    public void Dispose() { done.Set(); thread.Join(5000); ready.Dispose(); done.Dispose(); }
}
'@
$assembly = [Reflection.Assembly]::LoadFrom((Resolve-Path -LiteralPath $AgentDll).Path)
$diagnostics = $assembly.GetType('AgentDiagnostics', $true)
$rootField = $diagnostics.GetField('_testRoot', [Reflection.BindingFlags]'NonPublic,Static')
$recordMethod = $diagnostics.GetMethod('Record')
$readMethod = $diagnostics.GetMethod('ReadRecent')
$armMethod = $diagnostics.GetMethod('ArmCapture')
$captureMethod = $diagnostics.GetMethod('CaptureRaster')
$sandbox = Join-Path ([IO.Path]::GetTempPath()) ('Baseer-Diagnostics-Test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($sandbox) | Out-Null
$script:passed = 0
function Check([bool]$Value, [string]$Name) {
    if (!$Value) { throw "FAIL: $Name" }
    $script:passed++
    Write-Output "DIAGNOSTICS=PASS CASE=$Name"
}
function Set-Root([string]$Name) {
    $path = Join-Path $sandbox $Name
    $rootField.SetValue($null, $path)
    return $path
}
function Record([int]$Id, [string]$Stage = 'claim', [string]$Code = 'claimed', [Exception]$Error = $null) {
    $recordMethod.Invoke($null, @($Id, $Stage, $Code, $Error, $null, $null, $null, $null, $null)) | Out-Null
}
function Recent { return ,($readMethod.Invoke($null, @())) }
try {
    $root = Set-Root 'redaction'
    $secret = 'NEVER_EXPORT_customer_mobile_token_123456'
    Record 42 $secret $secret ([InvalidOperationException]::new($secret))
    $events = Recent
    $json = $events | ConvertTo-Json -Depth 5
    Check (!$json.Contains($secret)) 'supplied-text-and-exception-message-redacted'
    Check ($events.Count -eq 1 -and $events[0].JobId -eq 42 -and $events[0].Code -eq 'unknown') 'safe-fallback-and-job-correlation'
    Check ($events[0].ExceptionType -eq 'InvalidOperationException' -and $null -ne $events[0].HResult) 'exception-type-and-hresult-retained'
    $fingerprint = 'a' * 64
    $recordMethod.Invoke($null, @(43, 'queue', 'queue_error', $null, 867, 2, $fingerprint, 576, 1023)) | Out-Null
    $latest = (Recent)[0]
    Check ($latest.WindowsJobId -eq 867 -and $latest.NativeStatus -eq 2 -and $latest.Fingerprint -eq $fingerprint) 'queue-and-raster-metadata-retained'
    Check ($latest.Width -eq 576 -and $latest.Height -eq 1023) 'raster-dimensions-retained'
    [IO.File]::WriteAllText((Join-Path $root 'config.json'), $secret)
    [IO.File]::WriteAllText((Join-Path $root 'agent.log'), $secret)
    $zipPath = Join-Path $sandbox 'support.zip'
    $diagnostics.GetMethod('Export').Invoke($null, @([string]$zipPath)) | Out-Null
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        Check ($archive.Entries.Count -eq 3) 'export-exact-allowlist'
        $exported = ''
        foreach ($entry in $archive.Entries) {
            $reader = [IO.StreamReader]::new($entry.Open())
            try { $exported += $reader.ReadToEnd() } finally { $reader.Dispose() }
        }
        Check (!$exported.Contains($secret)) 'export-excludes-config-logs-and-secrets'
        Check ($exported.Contains('paper_confirmation') -and $exported.Contains('unavailable')) 'export-never-claims-physical-paper'
    } finally { $archive.Dispose() }

    $root = Set-Root 'corrupt'
    Record 1
    $journal = Join-Path $root 'events.jsonl'
    [IO.File]::AppendAllText($journal, "{invalid-json`n" + ('x' * 10000) + "`n")
    $malicious = @{ Utc = [DateTimeOffset]::UtcNow.ToString('o'); JobId = 3; Stage = $secret; Code = $secret; ExceptionType = $secret; Fingerprint = $secret } | ConvertTo-Json -Compress
    [IO.File]::AppendAllText($journal, $malicious + "`n")
    Record 2
    $events = Recent
    Check ($events.Count -eq 3) 'corrupt-and-oversized-lines-skipped-with-later-records-readable'
    Check (!(($events | ConvertTo-Json -Depth 5).Contains($secret))) 'read-sanitizes-tampered-journal'
    $old = @{ Utc = [DateTimeOffset]::UtcNow.AddDays(-8).ToString('o'); JobId = 99; Stage = 'claim'; Code = 'claimed' } | ConvertTo-Json -Compress
    [IO.File]::AppendAllText($journal, $old + "`n")
    Check (@((Recent) | Where-Object JobId -eq 99).Count -eq 0) 'events-expire-after-seven-days'

    $root = Set-Root 'rotation'
    $watch = [Diagnostics.Stopwatch]::StartNew()
    for ($index = 1; $index -le 12000; $index++) { Record $index }
    $watch.Stop()
    $files = @(Get-ChildItem -LiteralPath $root -Filter '*.jsonl')
    Check ($files.Count -eq 2 -and @($files | Where-Object Length -gt 1048576).Count -eq 0) 'journal-rotation-capped-two-times-one-MiB'
    $events = Recent
    Check ($events.Count -eq 200 -and $events[0].JobId -eq 12000) 'recent-reading-capped-and-newest-first'
    Write-Output ('DIAGNOSTICS_APPEND_AVERAGE_MS=' + [Math]::Round($watch.Elapsed.TotalMilliseconds / 12000, 3))
    [IO.File]::SetLastWriteTimeUtc((Join-Path $root 'events.previous.jsonl'), [DateTime]::UtcNow.AddDays(-8))
    Record 12001
    Check (!(Test-Path -LiteralPath (Join-Path $root 'events.previous.jsonl'))) 'expired-rotated-file-removed'

    $blocked = Join-Path $sandbox 'not-a-directory'
    [IO.File]::WriteAllText($blocked, 'disk fault fixture')
    $rootField.SetValue($null, $blocked)
    Record 1
    Check ((Recent).Count -eq 0) 'storage-failure-does-not-throw-from-print-diagnostics'
    Check (!$armMethod.Invoke($null, @())) 'capture-arm-storage-failure-reported'

    $root = Set-Root 'lock-contention'
    $keyBytes = [Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($root).ToUpperInvariant())
    $mutexName = 'Local\BaseerPrintDiagnostics-' + [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($keyBytes))
    $holder = [DiagnosticMutexFixture]::new($mutexName)
    try {
        $elapsed = [Diagnostics.Stopwatch]::StartNew()
        Record 1
        $elapsed.Stop()
        Check ($elapsed.ElapsedMilliseconds -lt 1000) 'diagnostics-do-not-block-printing-on-store-lock-contention'
    } finally { $holder.Dispose() }
    Record 2
    Check ((Recent).Count -eq 1 -and (Recent)[0].JobId -eq 2) 'journal-recovers-after-lock-contention'

    $root = Set-Root 'capture'
    $bitmap = [Drawing.Bitmap]::new(200, 120)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([Drawing.Color]::White)
    $graphics.FillRectangle([Drawing.Brushes]::Black, 8, 8, 16, 16)
    $graphics.Dispose()
    $memory = [IO.MemoryStream]::new()
    $bitmap.Save($memory, [Drawing.Imaging.ImageFormat]::Jpeg)
    $original = $memory.ToArray()
    $memory.Dispose()
    try {
        $captureMethod.Invoke($null, @(1, $original, $bitmap)) | Out-Null
        Check (!(Test-Path -LiteralPath (Join-Path $root 'captures'))) 'capture-off-by-default'
        Check ($armMethod.Invoke($null, @())) 'capture-explicit-arm'
        for ($index = 1; $index -le 4; $index++) {
            $captureMethod.Invoke($null, @($index, $original, $bitmap)) | Out-Null
        }
        $folders = @(Get-ChildItem -LiteralPath (Join-Path $root 'captures') -Directory)
        Check ($folders.Count -eq 3) 'capture-limited-to-three-jobs'
        Check (!$armMethod.Invoke($null, @())) 'rearming-cannot-bypass-retained-job-limit'
        $evidence = Get-Content -LiteralPath (Join-Path $folders[0].FullName 'evidence.json') -Raw | ConvertFrom-Json
        $hash = (Get-FileHash -LiteralPath (Join-Path $folders[0].FullName 'original.jpg') -Algorithm SHA256).Hash.ToLowerInvariant()
        Check ($evidence.original_sha256 -eq $hash -and $evidence.width -eq 200) 'capture-retains-source-hash-and-pixel-dimensions'
        $captureZip = Join-Path $sandbox 'capture-support.zip'
        $diagnostics.GetMethod('Export').Invoke($null, @([string]$captureZip)) | Out-Null
        $archive = [IO.Compression.ZipFile]::OpenRead($captureZip)
        try { Check (@($archive.Entries | Where-Object FullName -Match '\.(png|jpg)$').Count -eq 0) 'capture-images-excluded-from-default-export' }
        finally { $archive.Dispose() }
        foreach ($folder in $folders) { [IO.Directory]::SetLastWriteTimeUtc($folder.FullName, [DateTime]::UtcNow.AddHours(-25)) }
        $null = Recent
        Check (@(Get-ChildItem -LiteralPath (Join-Path $root 'captures') -Directory).Count -eq 0) 'captures-expire-after-twenty-four-hours'
        Check ($armMethod.Invoke($null, @())) 'capture-can-rearm-after-expiry'
        [IO.File]::WriteAllText((Join-Path $root 'capture-arm.json'), '{"Until":"2000-01-01T00:00:00Z","Remaining":3}')
        $captureMethod.Invoke($null, @(5, $original, $bitmap)) | Out-Null
        Check (@(Get-ChildItem -LiteralPath (Join-Path $root 'captures') -Directory).Count -eq 0) 'expired-arm-does-not-capture'

        $sizeFolder = Join-Path $root 'captures/job-size-fixture'
        [IO.Directory]::CreateDirectory($sizeFolder) | Out-Null
        $sizeFile = [IO.FileStream]::new((Join-Path $sizeFolder 'processed.png'), [IO.FileMode]::CreateNew)
        try { $sizeFile.SetLength(20 * 1024 * 1024) } finally { $sizeFile.Dispose() }
        $null = $armMethod.Invoke($null, @())
        $captureMethod.Invoke($null, @(6, $original, $bitmap)) | Out-Null
        Check (@(Get-ChildItem -LiteralPath (Join-Path $root 'captures') -Directory).Count -eq 1) 'capture-total-size-cap-enforced'
    } finally { $bitmap.Dispose() }
    $arabic = $diagnostics.GetMethod('Action').Invoke($null, @('outcome_unknown', $true))
    $english = $diagnostics.GetMethod('Action').Invoke($null, @('outcome_unknown', $false))
    Check ($arabic.Length -gt 10 -and $english.Contains('avoid duplicates')) 'actionable-bilingual-unknown-outcome-guidance'
    foreach ($code in @('storage_failed', 'protocol_failed', 'prepare_failed')) {
        Record 72 'prepare' $code
        $event = (Recent)[0]
        $description = $diagnostics.GetMethod('Describe').Invoke($null, @([string]$code, $false))
        $action = $diagnostics.GetMethod('Action').Invoke($null, @([string]$code, $false))
        Check ($event.Code -eq $code -and $description -ne $code.Replace('_', ' ') -and $action.Length -gt 20) "precise-error-catalog-$code"
    }
    $started = $diagnostics.GetMethod('Describe').Invoke($null, @('started', $false))
    Check ($started.Contains('not yet confirmed')) 'runtime-start-never-claims-server-contact'
    Write-Output "DIAGNOSTICS_TESTS_PASSED=$script:passed"
    Write-Output "DIAGNOSTICS_TEST_EVIDENCE=$sandbox"
} finally {
    $rootField.SetValue($null, $null)
    # Preserve isolated synthetic evidence for review; production storage is never touched.
}
