@echo off
set "BASEER_PWSH=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe"
if exist "%BASEER_PWSH%" (
  start "" "%BASEER_PWSH%" -NoProfile -STA -WindowStyle Hidden -File "%~dp0Connect-Baseer.ps1"
) else (
  start "" powershell.exe -NoProfile -STA -WindowStyle Hidden -File "%~dp0Connect-Baseer.ps1"
)
