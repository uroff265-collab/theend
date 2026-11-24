# TheEnd one-click launcher for Windows / LDPlayer
$ErrorActionPreference = "Stop"
$Repo = "https://raw.githubusercontent.com/uroff265-collab/theend/main"
$Folder = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Folder

Write-Host "=== TheEnd Bot: запуск ===" -ForegroundColor Cyan

# Prepare OCR/OpenCV dependencies and language data on first run.
$Setup = Join-Path $Folder "install_theend.ps1"
Invoke-WebRequest "$Repo/install_theend.ps1" -OutFile $Setup
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Setup
if ($LASTEXITCODE -ne 0) { throw "Первичная настройка TheEnd завершилась ошибкой." }

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
Write-Host "Обновляю агент из GitHub..."
Invoke-WebRequest "$Repo/theend_agent.py" -OutFile $Agent
$Vision = Join-Path $Folder "theend_vision.py"
Invoke-WebRequest "$Repo/theend_vision.py" -OutFile $Vision

# Fail early with a clear message if either Python module was not downloaded.
foreach ($RequiredFile in @($Agent, $Vision)) {
  if (-not (Test-Path $RequiredFile) -or (Get-Item $RequiredFile).Length -lt 100) {
    throw "Не удалось загрузить обязательный файл: $RequiredFile. Проверь интернет и запусти START_THEEND.bat ещё раз."
  }
}
Write-Host "Файлы агента:"
Get-Item $Agent, $Vision | Select-Object Name, Length | Format-Table -AutoSize
& py -3 -c "import os,sys; sys.path.insert(0, r'$Folder'); import theend_vision; print('Модуль распознавания загружен:', os.path.basename(theend_vision.__file__))"
if ($LASTEXITCODE -ne 0) {
  throw "Python не видит theend_vision.py в папке проекта. Проверь, что оба файла лежат рядом."
}

$Adb = if (Test-Path "C:\platform-tools\adb.exe") { "C:\platform-tools\adb.exe" } else { "adb" }
Write-Host "Проверяю ADB..."
& $Adb start-server | Out-Null
& $Adb connect "127.0.0.1:5555" | Out-Null
$Devices = & $Adb devices
if (-not ($Devices -match "127\.0\.0\.1:5555\s+device")) {
  Write-Host "LDPlayer не подключён. Открой LDPlayer и включи ADB (порт 5555)." -ForegroundColor Red
  Read-Host "Нажми Enter для выхода"
  exit 1
}

# Verify that ADB can capture the emulator screen before starting automation.
$null = & $Adb -s "127.0.0.1:5555" exec-out screencap -p
if ($LASTEXITCODE -ne 0) {
  Write-Host "ADB подключён, но не может получить экран. Перезапусти LDPlayer." -ForegroundColor Red
  Read-Host "Нажми Enter для выхода"
  exit 1
}

Write-Host "Эмулятор доступен. Запускаю актуальный TheEnd Agent..." -ForegroundColor Green
Write-Host "Для остановки нажми Ctrl+C."
py $Agent
if ($LASTEXITCODE -ne 0) {
  Write-Host "Агент завершился с ошибкой: $LASTEXITCODE" -ForegroundColor Red
  Read-Host "Нажми Enter для выхода"
}
