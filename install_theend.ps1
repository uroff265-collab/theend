# TheEnd first-run setup for Windows + LDPlayer
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Write-Host "=== TheEnd Windows setup ===" -ForegroundColor Cyan

$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) { throw "Python Launcher (py.exe) not found. Install Python 3.11+ and enable Add Python to PATH." }
& py -3 -c "import sys; print('Python', sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Python 3 could not be started." }

Write-Host "Installing agent Python packages..."
& py -3 -m pip install --user --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& py -3 -m pip install --user pytesseract pillow opencv-python-headless numpy
if ($LASTEXITCODE -ne 0) { throw "OCR/OpenCV package installation failed." }

$Tesseract = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (-not (Test-Path $Tesseract)) {
  $TesseractCommand = Get-Command tesseract.exe -ErrorAction SilentlyContinue
  if ($TesseractCommand) { $Tesseract = $TesseractCommand.Source } else { $Tesseract = $null }
}
if (-not $Tesseract -or -not (Test-Path $Tesseract)) {
  throw "Tesseract OCR 5 was not found. Install it for Windows, then run the launcher again."
}

$DataDir = Join-Path $env:LOCALAPPDATA "TheEnd\tessdata"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
foreach ($Language in @("eng","rus")) {
  $Model = Join-Path $DataDir "$Language.traineddata"
  if (-not (Test-Path $Model)) {
    Write-Host "Downloading OCR language model: $Language"
    $Url = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$Language.traineddata"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Model
  }
  if ((Get-Item $Model).Length -lt 100000) { throw "OCR model $Language is incomplete." }
}

$env:TESSDATA_PREFIX = $DataDir
$env:PATH = (Split-Path $Tesseract) + ";" + $env:PATH
& $Tesseract --list-langs --tessdata-dir $DataDir
if ($LASTEXITCODE -ne 0) { throw "Tesseract could not load the language models." }

$Adb = "C:\platform-tools\adb.exe"
if (-not (Test-Path $Adb)) {
  $AdbCommand = Get-Command adb.exe -ErrorAction SilentlyContinue
  if ($AdbCommand) { $Adb = $AdbCommand.Source } else { $Adb = $null }
}
if (-not $Adb -or -not (Test-Path $Adb)) { throw "ADB was not found. Check C:\platform-tools\adb.exe." }

Write-Host "Python dependencies and OCR setup are ready." -ForegroundColor Green
Write-Host "Tesseract: $Tesseract"
Write-Host "OCR data: $DataDir"
Write-Host "ADB: $Adb"
