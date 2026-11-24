@echo off
title TheEnd V19 - fresh diagnostic launcher
set "WORK=%TEMP%\TheEnd_V19"
if not exist "%WORK%" mkdir "%WORK%"
echo Downloading fresh TheEnd V19 launcher...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/uroff265-collab/theend/10be86165153be242bb82a231e139b66519d104a/start_theend.ps1' -OutFile (Join-Path $env:TEMP 'TheEnd_V19\start_theend.ps1'); Write-Host 'Fresh launcher downloaded to %TEMP%\TheEnd_V19' "
if errorlevel 1 (
  echo Failed to download the fresh launcher.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WORK%\start_theend.ps1"
pause
