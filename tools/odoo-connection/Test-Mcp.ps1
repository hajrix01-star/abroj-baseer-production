#Requires -Version 5.1
$ErrorActionPreference='Stop'
$runtime=(Get-Process -Id $PID).Path
$start=New-Object Diagnostics.ProcessStartInfo
$start.FileName=$runtime
$start.Arguments='-NoProfile -File "'+(Join-Path $PSScriptRoot 'Start-BaseerMcp.ps1')+'"'
$start.UseShellExecute=$false
$start.CreateNoWindow=$true
$start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
$process=New-Object Diagnostics.Process
$process.StartInfo=$start
[void]$process.Start()
$stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
$frames=@(
    '{"jsonrpc":"2.0","id":0,"method":"tools/list"}',
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}',
    '{"jsonrpc":"2.0","method":"notifications/initialized"}',
    '{"jsonrpc":"2.0","id":2,"method":"ping"}',
    '{"jsonrpc":"2.0","id":3,"method":"tools/list"}',
    '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"baseer_connection_status","arguments":{}}}',
    '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"baseer_payroll_read","arguments":{"model":"res.users","method":"write","fields":["FAKE-SECRET-MUST-NOT-ECHO"]}}}',
    '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"arbitrary_method","arguments":{}}}',
    '{"jsonrpc":"2.0","id":7,"method":"unknown"}',
    '{"jsonrpc":"2.0","method":"notifications/unknown"}',
    'INVALID-FAKE-SECRET-MUST-NOT-ECHO',
    ('x'*65537)
)
foreach($frame in $frames){$process.StandardInput.WriteLine($frame)}
$process.StandardInput.Close()
if(-not $process.WaitForExit(15000)){$process.Kill();throw 'MCP test timed out.'}
$output=$stdout.GetAwaiter().GetResult();$errors=$stderr.GetAwaiter().GetResult()
if($process.ExitCode -ne 0 -or $errors.Length){throw 'MCP startup produced unexpected errors.'}
$lines=@($output -split '\r?\n' | Where-Object Length -gt 0)
if($lines.Count -ne 10){throw ('Unexpected response count: '+$lines.Count)}
$messages=@($lines | ForEach-Object {ConvertFrom-Json -InputObject $_})
foreach($message in $messages){if($message.jsonrpc -cne '2.0'){throw 'Non-protocol stdout.'}}
if($messages[0].error.code -ne -32600){throw 'Lifecycle guard failed.'}
if($messages[1].result.protocolVersion -cne '2025-06-18'){throw 'Negotiation failed.'}
if($messages[3].result.tools.Count -ne 3){throw 'Unexpected tool surface.'}
if($messages[4].result.isError){throw 'Status should be available without credentials.'}
if(-not $messages[5].result.isError -or -not $messages[6].result.isError){throw 'Unsafe tool call was accepted.'}
if($messages[7].error.code -ne -32601){throw 'Unknown RPC guard failed.'}
if($output.Contains('FAKE-SECRET-MUST-NOT-ECHO')){throw 'Input leaked into protocol error.'}
$process.Dispose()
Write-Output 'PASS: MCP lifecycle, three tools, notifications, status, invalid calls, oversized/malformed frames, sanitized errors; no Odoo calls.'
