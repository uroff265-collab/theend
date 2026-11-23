# TheEnd first-run setup for Windows + LDPlayer
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Write-Host "=== TheEnd: подготовка Windows ===" -ForegroundColor Cyan

$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) { throw "Python Launcher (py.exe) не найден. Установи Python 3.11+ с python.org и отметь Add Python to PATH." }
& py -3 -c "import sys; print('Python', sys.version)"
if ($LASTEXITCODE -ne 0) { throw "Не удалось запустить Python 3." }

Write-Host "Проверяю и устанавливаю библиотеки агента..."
& py -3 -m pip install --user --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Не удалось обновить pip." }
& py -3 -m pip install --user pytesseract pillow opencv-python-headless numpy
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить библиотеки OCR/OpenCV." }

$Tesseract = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (-not (Test-Path $Tesseract)) {
  $Tesseract = (Get-Command tesseract.exe -ErrorAction SilentlyContinue).Source
}
if (-not $Tesseract -or -not (Test-Path $Tesseract)) {
  throw "Tesseract OCR не найден. Установи Tesseract OCR 5 для Windows, затем запусти START_THEEND.bat снова."
}

$DataDir = Join-Path $env:LOCALAPPDATA "TheEnd\tessdata"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
foreach ($Language in @("eng","rus")) {
  $Model = Join-Path $DataDir "$Language.traineddata"
  if (-not (Test-Path $Model)) {
    Write-Host "Загружаю языковую модель OCR: $Language"
    $Url = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$Language.traineddata"
    Invoke-WebRequest -Uri $Url -OutFile $Model
  }
  if ((Get-Item $Model).Length -lt 100000) { throw "Файл OCR $Language повреждён или неполный." }
}

$env:TESSDATA_PREFIX = $DataDir
$env:PATH = (Split-Path $Tesseract) + ";" + $env:PATH
& $Tesseract --list-langs --tessdata-dir $DataDir
if ($LASTEXITCODE -ne 0) { throw "Tesseract не смог загрузить языковые модели." }

$Adb = "C:\platform-tools\adb.exe"
if (-not (Test-Path $Adb)) { $Adb = (Get-Command adb.exe -ErrorAction SilentlyContinue).Source }
if (-not $Adb -or -not (Test-Path $Adb)) { throw "ADB не найден. Проверь C:\platform-tools\adb.exe." }

Write-Host "Проверка Python-зависимостей завершена." -ForegroundColor Green
Write-Host "Tesseract: $Tesseract"
Write-Host "OCR-модели: $DataDir"
Write-Host "ADB: $Adb"
