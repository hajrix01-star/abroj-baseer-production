param(
    [string]$EmulatorSerial = 'emulator-5554',
    [string]$GradleBin = 'D:\Codex\tools\gradle-8.11.1\bin\gradle.bat',
    [string]$SdkRoot = 'D:\Codex\AndroidSdk',
    [string]$ExpectedSourceCommit = $env:BCHAT_SOURCE_COMMIT,
    [string]$ExpectedSourceBranch = $env:BCHAT_SOURCE_BRANCH,
    [int]$PreviousVersionCode = 87,
    [switch]$SkipDeviceInstall
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceRoot = (& git -C $project rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0) { throw 'A Git source checkout is required.' }
$sourceCommit = (& git -C $sourceRoot rev-parse HEAD).Trim()
if ($ExpectedSourceCommit -notmatch '^[0-9a-f]{40}$' -or $sourceCommit -ne $ExpectedSourceCommit) {
    throw 'Pass the exact reviewed source commit through -ExpectedSourceCommit or BCHAT_SOURCE_COMMIT.'
}
$sourceBranch = ([string](& git -C $sourceRoot symbolic-ref --quiet --short HEAD)).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ExpectedSourceBranch) -or
    $sourceBranch -ne $ExpectedSourceBranch) {
    throw 'Pass the reviewed source branch through -ExpectedSourceBranch or BCHAT_SOURCE_BRANCH; detached HEAD is not accepted.'
}
$sourceStatus = & git -C $sourceRoot status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0 -or $sourceStatus) {
    throw 'The reviewed release checkout must be clean, including untracked source files.'
}
$sourceEpoch = (& git -C $sourceRoot show -s --format=%ct HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceEpoch -notmatch '^[0-9]+$') { throw 'Missing source timestamp.' }
$env:BCHAT_SOURCE_COMMIT = $sourceCommit
$env:SOURCE_DATE_EPOCH = $sourceEpoch
if ($EmulatorSerial -notmatch '^emulator-[0-9]+$') {
    throw 'Only an Android emulator may be updated by this script.'
}
# Use only the documented local store, never a filesystem/history search or a fallback key.
$signingRoot = Join-Path $env:LOCALAPPDATA 'Baseer\BChatSigning\fresh-install-20261009'
if ([string]::IsNullOrWhiteSpace($env:BCHAT_SIGNING_KEY)) {
    $env:BCHAT_SIGNING_KEY = Join-Path $signingRoot 'bchat-preview-fresh.p12'
}
if ([string]::IsNullOrWhiteSpace($env:BCHAT_SIGNING_PASSWORD_FILE)) {
    $env:BCHAT_SIGNING_PASSWORD_FILE = Join-Path $signingRoot 'keystore.password'
}
if ([string]::IsNullOrWhiteSpace($env:BCHAT_SIGNING_KEY) -or
    [string]::IsNullOrWhiteSpace($env:BCHAT_SIGNING_PASSWORD_FILE) -or
    -not (Test-Path -LiteralPath $env:BCHAT_SIGNING_KEY) -or
    -not (Test-Path -LiteralPath $env:BCHAT_SIGNING_PASSWORD_FILE)) {
    throw 'Set BCHAT_SIGNING_KEY and BCHAT_SIGNING_PASSWORD_FILE to the existing preview signing files.'
}

$firebaseConfig = Join-Path $project 'app\google-services.json'
if (-not (Test-Path -LiteralPath $firebaseConfig)) {
    throw 'Firebase configuration is missing; refusing a silently reduced push-enabled APK.'
}
$adb = Join-Path $SdkRoot 'platform-tools\adb.exe'
$aapt = Join-Path $SdkRoot 'build-tools\35.0.0\aapt.exe'
$apksigner = Join-Path $SdkRoot 'build-tools\35.0.0\apksigner.bat'
$expectedSigner = 'f4a5a07e49fdcf9f0e5d5112bbd318636a2bc566329163aec7bcd71b44e3158c'
Push-Location $project
try {
    & $GradleBin :app:assembleRelease :app:lintRelease -PbchatEnablePush=true --offline
    if ($LASTEXITCODE -ne 0) { throw 'Release build or lint failed.' }
    $afterCommit = (& git -C $sourceRoot rev-parse HEAD).Trim()
    $afterBranch = ([string](& git -C $sourceRoot symbolic-ref --quiet --short HEAD)).Trim()
    $afterStatus = & git -C $sourceRoot status --porcelain --untracked-files=normal
    if ($LASTEXITCODE -ne 0 -or $afterCommit -ne $sourceCommit -or $afterBranch -ne $sourceBranch -or $afterStatus) {
        throw 'Source changed during the build; no artifact is accepted.'
    }

    $built = Join-Path $project 'app\build\outputs\apk\release\app-release.apk'
    $packageLine = (& $aapt dump badging $built | Where-Object { $_ -match '^package:' } | Select-Object -First 1)
    $versionMatch = [regex]::Match([string]$packageLine, "name='com\.baseer\.bchat\.preview' versionCode='([0-9]+)'")
    if ($LASTEXITCODE -ne 0 -or -not $versionMatch.Success) {
        throw 'Unexpected package identity or missing versionCode.'
    }
    $versionCode = $versionMatch.Groups[1].Value
    if ($PreviousVersionCode -lt 87 -or [int]$versionCode -le $PreviousVersionCode) {
        throw 'The unified APK must increment versionCode beyond the previously distributed build.'
    }
    $manifestTree = & $aapt dump xmltree $built AndroidManifest.xml
    if ($LASTEXITCODE -ne 0 -or
        -not ($manifestTree | Select-String -Quiet -SimpleMatch 'com.baseer.freshchat.BChatFirebaseMessagingService') -or
        -not ($manifestTree | Select-String -Quiet -SimpleMatch 'com.google.firebase.MESSAGING_EVENT')) {
        throw 'The built APK is missing the Firebase messaging service; refusing a silently reduced release.'
    }
    $signature = & $apksigner verify --print-certs $built
    if ($LASTEXITCODE -ne 0 -or
        -not ($signature | Where-Object { $_ -eq "Signer #1 certificate SHA-256 digest: $expectedSigner" })) {
        throw 'Release APK signature does not match the approved preview certificate.'
    }

    $artifactDir = Join-Path $project 'artifacts'
    New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
    $artifact = Join-Path $artifactDir "BChat-phone-v$versionCode-unified.apk"
    if (Test-Path -LiteralPath $artifact) { throw "Refusing to overwrite $artifact" }
    Copy-Item -LiteralPath $built -Destination $artifact
    $expectedHash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash
    $versionNameMatch = [regex]::Match([string]$packageLine, "versionName='([^']+)'")
    $targetLine = & $aapt dump badging $artifact | Where-Object { $_ -match '^targetSdkVersion:' } | Select-Object -First 1
    $releaseManifest = [ordered]@{
        schema = 1
        sourceCommit = $sourceCommit
        sourceBranch = $sourceBranch
        sourceDateEpoch = $sourceEpoch
        package = 'com.baseer.bchat.preview'
        versionCode = [int]$versionCode
        versionName = $versionNameMatch.Groups[1].Value
        targetSdk = ([regex]::Match([string]$targetLine, "'([0-9]+)'")).Groups[1].Value
        sha256 = $expectedHash.ToLowerInvariant()
        signerSha256 = $expectedSigner
        firebaseMessagingVerified = $true
        deviceValidation = 'not-run'
    }
    $manifestPath = "$artifact.manifest.json"
    if (Test-Path -LiteralPath $manifestPath) { throw 'Refusing to overwrite a release manifest.' }
    $releaseManifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8

    if ($SkipDeviceInstall) {
        Write-Output "Unified APK: $artifact"
        Write-Output "SHA256: $expectedHash"
        Write-Output 'Device validation: skipped explicitly; this is artifact validation, not device acceptance.'
        return
    }

    & $adb -s $EmulatorSerial install -r $artifact
    if ($LASTEXITCODE -ne 0) { throw 'Installing the unified APK failed.' }
    $remote = (& $adb -s $EmulatorSerial shell pm path com.baseer.bchat.preview | Select-Object -First 1) -replace '^package:', ''
    $remote = $remote.Trim()
    if (-not $remote.StartsWith('/data/app/')) { throw 'Installed APK path is unexpected.' }

    $verifyCopy = Join-Path $project "artifacts\installed-check-$versionCode-$([guid]::NewGuid().ToString('N')).apk"
    try {
        & $adb -s $EmulatorSerial pull $remote $verifyCopy
        if ($LASTEXITCODE -ne 0) { throw 'Could not read back the installed APK.' }
        $installedHash = (Get-FileHash -LiteralPath $verifyCopy -Algorithm SHA256).Hash
        if ($installedHash -ne $expectedHash) { throw 'Emulator APK differs from the phone artifact.' }
    } finally {
        if (Test-Path -LiteralPath $verifyCopy) { Remove-Item -LiteralPath $verifyCopy }
    }
    $releaseManifest.deviceValidation = "identical-apk-installed:$EmulatorSerial"
    $releaseManifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8
    Write-Output "Unified APK: $artifact"
    Write-Output "SHA256: $expectedHash"
    Write-Output "Emulator: $EmulatorSerial (identical APK)"
} finally {
    Pop-Location
}
