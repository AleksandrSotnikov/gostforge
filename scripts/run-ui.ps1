<#
.SYNOPSIS
    run-ui.ps1 — нативное развёртывание и запуск веб-интерфейса gostforge
    (без Docker). Python вызывается через лаунчер `py`.

.DESCRIPTION
    Создаёт виртуальное окружение (`py -3 -m venv .venv`), ставит проект с
    extra [ui] и запускает Streamlit-интерфейс. python.exe берётся прямо из
    venv — скрипт НЕ зависит от активации, политики выполнения PowerShell и
    не цепляет Store-заглушку `python`.

    ВАЖНО: файл сохранён в UTF-8 с BOM — иначе Windows PowerShell 5.1 читает
    кириллицу в кодировке cp1251 и падает с ошибкой парсинга.

.PARAMETER Port
    Порт веб-интерфейса (по умолчанию 8501).

.PARAMETER Reinstall
    Пересоздать .venv и переустановить зависимости с нуля.

.PARAMETER NoLaunch
    Только установить окружение, без запуска UI.

.EXAMPLE
    .\scripts\run-ui.ps1
.EXAMPLE
    .\scripts\run-ui.ps1 -Port 8600 -Reinstall
#>
[CmdletBinding()]
param(
    [int]$Port = 8501,
    [switch]$Reinstall,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'

function Write-Info { param([string]$m) Write-Host "[*] $m" -ForegroundColor Blue }
function Write-Ok { param([string]$m) Write-Host "[+] $m" -ForegroundColor Green }
function Write-Err { param([string]$m) Write-Host "[x] $m" -ForegroundColor Red }

# Корень репозитория: scripts\ -> на уровень выше.
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
Write-Info "Корень проекта: $root"

# 1. Проверяем лаунчер py.
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Err "Лаунчер 'py' не найден."
    Write-Err "Установите Python 3.11+ с https://www.python.org/downloads/,"
    Write-Err "отметив 'py launcher' и 'Add python.exe to PATH', и перезапустите PowerShell."
    exit 1
}
$pyVer = (& py -3 --version) 2>&1
Write-Info "Python: $pyVer"

# 2. Виртуальное окружение.
$venv = Join-Path $root '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if ($Reinstall -and (Test-Path $venv)) {
    Write-Info "Удаляю старое окружение (-Reinstall)..."
    Remove-Item -Recurse -Force $venv
}
if (-not (Test-Path $venvPy)) {
    Write-Info "Создаю виртуальное окружение (.venv)..."
    & py -3 -m venv $venv
    if (-not (Test-Path $venvPy)) {
        Write-Err "Не удалось создать venv: $venvPy не появился."
        Write-Err "Проверьте установку Python (py -3 -m venv .venv) вручную."
        exit 1
    }
}
else {
    Write-Info "Окружение .venv уже есть (пересоздать: -Reinstall)."
}

# 3. Установка зависимостей (через python из venv — без активации,
#    поэтому 'pip' не нужен и ошибка launcher-а pip.exe исключена).
Write-Info "Обновляю pip..."
& $venvPy -m pip install --upgrade pip
Write-Info "Устанавливаю gostforge[ui] (editable)..."
& $venvPy -m pip install -e ".[ui]"
if ($LASTEXITCODE -ne 0) {
    Write-Err "Установка зависимостей не удалась (см. вывод выше)."
    exit 1
}
Write-Ok "Зависимости установлены."

# 4. Запуск веб-интерфейса.
if ($NoLaunch) {
    Write-Ok "Готово (без запуска). Запуск вручную:"
    Write-Host "    & '$venvPy' -m streamlit run src\gostforge\web\app.py --server.port $Port"
    exit 0
}
$app = Join-Path $root 'src\gostforge\web\app.py'
Write-Ok "Запускаю веб-интерфейс: http://localhost:$Port  (Ctrl+C - остановить)"
& $venvPy -m streamlit run $app `
    --server.address localhost `
    --server.port $Port `
    --theme.base light `
    --theme.primaryColor "#2F5496"
