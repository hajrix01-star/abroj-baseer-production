param([Parameter(Mandatory=$true)][string]$AgentDll, [Parameter(Mandatory=$true)][string]$EvidenceDirectory)
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFrom((Resolve-Path -LiteralPath $AgentDll).Path)
$diagnostics = $assembly.GetType('AgentDiagnostics', $true)
$root = [IO.Path]::GetFullPath($EvidenceDirectory)
$diagnostics.GetField('_testRoot', [Reflection.BindingFlags]'NonPublic,Static').SetValue($null, $root)
$record = $diagnostics.GetMethod('Record')
# Synthetic local evidence only. This harness never starts a worker, pairs, or prints.
$record.Invoke($null, @($null, 'connection', 'heartbeat', $null, $null, $null, $null, $null, $null)) | Out-Null
$record.Invoke($null, @(42, 'queue', 'queue_paperout', $null, 867, 64, $null, $null, $null)) | Out-Null
$assembly.GetType('AgentStatusWindow', $true).GetMethod('Run').Invoke($null, @())
