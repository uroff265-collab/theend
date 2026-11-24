# TheEnd Windows / LDPlayer launcher. ASCII-only for Windows PowerShell 5.1.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoOwner = "uroff265-collab"
$RepoName = "theend"
$Branch = "main"
$Build = $null
$Repo = $null
$Folder = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Folder

try {
  Write-Host "=== TheEnd Agent launcher ===" -ForegroundColor Cyan
  Write-Host "Checking for the latest TheEnd version..."
  $Headers = @{ "User-Agent" = "TheEnd-Updater"; "Accept" = "application/vnd.github+json" }
  $CommitInfo = Invoke-RestMethod -Headers $Headers -Uri "https://api.github.com/repos/$RepoOwner/$RepoName/commits/$Branch"
  $Build = [string]$CommitInfo.sha
  if ($Build.Length -ne 40 -or $Build -match '[^0-9a-f]') { throw "GitHub returned an invalid build identifier." }
  $Repo = "https://raw.githubusercontent.com/$RepoOwner/$RepoName/$Build"
  Write-Host "Latest build: $Build" -ForegroundColor Yellow

  # Continue with files from this exact commit.
  $Setup = Join-Path $Folder "install_theend.ps1"
  Invoke-WebRequest -UseBasicParsing -Uri "$Repo/install_theend.ps1" -OutFile $Setup
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Setup
  if ($LASTEXITCODE -ne 0) { throw "Setup failed. Read the setup output above." }

  $env:TESSDATA_PREFIX = Join-Path $env:LOCALAPPDATA "TheEnd\tessdata"
  $TesseractDir = "C:\Program Files\Tesseract-OCR"
  if (Test-Path (Join-Path $TesseractDir "tesseract.exe")) {
    $env:PATH = $TesseractDir + ";" + $env:PATH
  }

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
  $Vision = Join-Path $Folder "theend_vision.py"
  Write-Host "Downloading approved agent files..."
  Invoke-WebRequest -UseBasicParsing -Uri "$Repo/theend_agent.py" -OutFile $Agent
  Invoke-WebRequest -UseBasicParsing -Uri "$Repo/theend_vision.py" -OutFile $Vision

  foreach ($RequiredFile in @($Agent, $Vision)) {
    if (-not (Test-Path $RequiredFile) -or (Get-Item $RequiredFile).Length -lt 100) {
      throw "Required agent file is missing or incomplete: $RequiredFile"
    }
  }

  $AgentText = Get-Content -Raw -Encoding UTF8 $Agent
  foreach ($Marker in @("TheEnd Agent v19", "def find_visual_resource_badges(png):", "0.620", "y0,y1=int(h*.025),int(h*.84)", "def diagnose_game_screen()")) {
    if (-not $AgentText.Contains($Marker)) {
      throw "Agent validation failed. Missing marker: $Marker"
    }
  }
  $AgentHash = (Get-FileHash -Algorithm SHA256 $Agent).Hash
  Write-Host "Agent source verified. SHA256: $AgentHash" -ForegroundColor Green

  Write-Host "Checking Python module import..."
  & py -3 -c "import theend_vision"
  if ($LASTEXITCODE -ne 0) { throw "Python could not import theend_vision.py." }

  $Adb = "C:\platform-tools\adb.exe"
  if (-not (Test-Path $Adb)) {
    $AdbCommand = Get-Command adb.exe -ErrorAction SilentlyContinue
    if ($AdbCommand) { $Adb = $AdbCommand.Source } else { throw "ADB was not found." }
  }

  Write-Host "Checking Android emulator connection..."
  & $Adb start-server | Out-Null
  & $Adb connect "127.0.0.1:5555" | Out-Null
  $Devices = & $Adb devices
  if (-not ($Devices -match "127\.0\.0\.1:5555\s+device")) {
    throw "LDPlayer is not connected on 127.0.0.1:5555. Open LDPlayer and enable ADB port 5555."
  }

  & $Adb -s "127.0.0.1:5555" exec-out screencap -p | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "ADB is connected but screenshot capture failed." }

  Write-Host "Emulator is ready. Starting TheEnd Agent..." -ForegroundColor Green
  Write-Host "Press Ctrl+C to stop."
  & py $Agent
  if ($LASTEXITCODE -ne 0) { throw "Agent exited with code $LASTEXITCODE." }
}
catch {
  Write-Host ""
  Write-Host ("THEEND ERROR: " + $_.Exception.Message) -ForegroundColor Red
  exit 1
}
