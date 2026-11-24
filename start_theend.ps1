# TheEnd one-click launcher for Windows / LDPlayer
$ErrorActionPreference = "Stop"
$Build = "bcfc73deea286f6d0cb6807d7ad6a8d5c239d8e2"
$Repo = "https://raw.githubusercontent.com/uroff265-collab/theend/$Build"
$Folder = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Folder

Write-Host "=== TheEnd Bot: starting ===" -ForegroundColor Cyan

# Prepare OCR/OpenCV dependencies and language data on first run.
$Setup = Join-Path $Folder "install_theend.ps1"
Invoke-WebRequest "$Repo/install_theend.ps1`?v=$Build" -OutFile $Setup
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Setup
if ($LASTEXITCODE -ne 0) { throw "TheEnd setup failed. See the setup messages above." }

# Set an unquoted tessdata directory for the child agent process.
$env:TESSDATA_PREFIX = Join-Path $env:LOCALAPPDATA "TheEnd\tessdata"
$TesseractDir = "C:\Program Files\Tesseract-OCR"
if (Test-Path (Join-Path $TesseractDir "tesseract.exe")) {
  $env:PATH = $TesseractDir + ";" + $env:PATH
}

# Stop only older TheEnd agent processes, not unrelated Python programs.
try {
  $old = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and
    $_.CommandLine -match 'theend_agent(_v\d+)?\.py'
  }
  foreach ($p in $old) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
} catch {}

$Agent = Join-Path $Folder "theend_agent.py"
Write-Host "Downloading agent files from GitHub..."
Invoke-WebRequest "$Repo/theend_agent.py`?v=$Build" -OutFile $Agent
$Vision = Join-Path $Folder "theend_vision.py"
Invoke-WebRequest "$Repo/theend_vision.py`?v=$Build" -OutFile $Vision

# Fail early with a clear message if either Python module was not downloaded.
foreach ($RequiredFile in @($Agent, $Vision)) {
  if (-not (Test-Path $RequiredFile) -or (Get-Item $RequiredFile).Length -lt 100) {
    throw "Required file is missing or incomplete: $RequiredFile. Check internet and run START_THEEND.bat again."
  }
}
Write-Host "Agent files:"
Get-Item $Agent, $Vision | Select-Object Name, Length | Format-Table -AutoSize
& py -3 -c "import os,sys; sys.path.insert(0, r'$Folder'); import theend_vision; print('Vision module loaded:', os.path.basename(theend_vision.__file__))"
if ($LASTEXITCODE -ne 0) {
  throw "Python cannot import theend_vision.py. Ensure both agent files are in the project folder."
}

$Adb = if (Test-Path "C:\platform-tools\adb.exe") { "C:\platform-tools\adb.exe" } else { "adb" }
Write-Host "Checking ADB..."
& $Adb start-server | Out-Null
& $Adb connect "127.0.0.1:5555" | Out-Null
$Devices = & $Adb devices
if (-not ($Devices -match "127\.0\.0\.1:5555\s+device")) {
  Write-Host "LDPlayer is not connected. Open LDPlayer and enable ADB on port 5555." -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

# Verify that ADB can capture the emulator screen before starting automation.
$null = & $Adb -s "127.0.0.1:5555" exec-out screencap -p
if ($LASTEXITCODE -ne 0) {
  Write-Host "ADB is connected but cannot capture the screen. Restart LDPlayer." -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

Write-Host "Emulator is ready. Starting TheEnd Agent..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop."
py $Agent
if ($LASTEXITCODE -ne 0) {
  Write-Host "Agent exited with error code: $LASTEXITCODE" -ForegroundColor Red
  Read-Host "Press Enter to exit"
}
