@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py tools\theend_support.py
) else (
  python tools\theend_support.py
)
if errorlevel 1 pause
