param(
    [string]$EmulatorSerial = 'emulator-5554',
    [string]$GradleBin = 'D:\Codex\tools\gradle-8.11.1\bin\gradle.bat',
    [string]$SdkRoot = 'D:\Codex\AndroidSdk'
)

$ErrorActionPreference = 'Stop'
if ($EmulatorSerial -notmatch '^emulator-[0-9]+$') {
    throw 'Only an Android emulator may be updated by this script.'
}
if ([string]::IsNullOrWhiteSpace($env:BCHAT_SIGNING_KEY) -or
    [string]::IsNullOrWhiteSpace($env:BCHAT_SIGNING_PASSWORD_FILE) -or
    -not (Test-Path -LiteralPath $env:BCHAT_SIGNING_KEY) -or
    -not (Test-Path -LiteralPath $env:BCHAT_SIGNING_PASSWORD_FILE)) {
    throw 'Set BCHAT_SIGNING_KEY and BCHAT_SIGNING_PASSWORD_FILE to the existing preview signing files.'
}

$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
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

    $built = Join-Path $project 'app\build\outputs\apk\release\app-release.apk'
    $packageLine = (& $aapt dump badging $built | Where-Object { $_ -match '^package:' } | Select-Object -First 1)
    $versionMatch = [regex]::Match([string]$packageLine, "name='com\.baseer\.bchat\.preview' versionCode='([0-9]+)'")
    if ($LASTEXITCODE -ne 0 -or -not $versionMatch.Success) {
        throw 'Unexpected package identity or missing versionCode.'
    }
    $versionCode = $versionMatch.Groups[1].Value
    $signature = & $apksigner verify --print-certs $built
    if ($LASTEXITCODE -ne 0 -or
        -not ($signature | Where-Object { $_ -eq "Signer #1 certificate SHA-256 digest: $expectedSigner" })) {
        throw 'Release APK signature does not match the approved preview certificate.'
    }

    $artifact = Join-Path $project "artifacts\BChat-phone-v$versionCode-unified.apk"
    if (Test-Path -LiteralPath $artifact) { throw "Refusing to overwrite $artifact" }
    Copy-Item -LiteralPath $built -Destination $artifact
    $expectedHash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash

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
    Write-Output "Unified APK: $artifact"
    Write-Output "SHA256: $expectedHash"
    Write-Output "Emulator: $EmulatorSerial (identical APK)"
} finally {
    Pop-Location
}
