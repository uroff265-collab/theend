@echo off
title TheEnd Launcher V18
set "LAUNCHER=https://raw.githubusercontent.com/uroff265-collab/theend/11f7236dc1ffc5d576381903d95539aa1f37ca03/start_theend.ps1"
set "PS1=%TEMP%\TheEnd_start_v18.ps1"
echo Downloading TheEnd V18 launcher...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing -Uri '%LAUNCHER%' -OutFile '%PS1%'"
if errorlevel 1 (
  echo Failed to download TheEnd launcher.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
pause
