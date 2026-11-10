param(
    [Parameter(Mandatory)][string]$Candidate
)

$ErrorActionPreference = 'Stop'
$profilePath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'BaseerPrintAgent-QA'
$config = Get-Content -LiteralPath (Join-Path $profilePath 'config.json') -Raw | ConvertFrom-Json
if ([uri]$config.ServerUrl -ne [uri]'https://baseer-live-qa.tail938958.ts.net/') {
    throw 'The isolated agent configuration must point to QA.'
}
$source = Get-Item -LiteralPath $Candidate
if ($source.Name -ne 'Baseer.PrintAgent.QA.exe') {
    throw 'Select a compiled QA profile executable.'
}
$versionInfo = $source.VersionInfo
$version = "$($versionInfo.FileMajorPart).$($versionInfo.FileMinorPart).$($versionInfo.FileBuildPart)"
$digest = (Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$updatePath = Join-Path $profilePath 'updates-v2'
$destination = Join-Path $updatePath "$version-$digest"
New-Item -Path $destination -ItemType Directory -Force | Out-Null
Copy-Item -LiteralPath $source.FullName -Destination (Join-Path $destination $source.Name)
$offer = [ordered]@{
    version = $version
    download_url = "https://github.com/hajrix01-star/abroj-baseer-production/releases/download/baseer-print-agent-$version/Baseer.PrintAgent.exe"
    sha256 = $digest
}
$temporary = Join-Path $updatePath ("qa-offer." + [guid]::NewGuid().ToString('N') + '.tmp')
[IO.File]::WriteAllText($temporary, ($offer | ConvertTo-Json -Compress))
[IO.File]::Move($temporary, (Join-Path $updatePath 'qa-offer.json'), $true)
$offer
