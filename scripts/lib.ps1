# lib.ps1 — общие функции для PowerShell-скриптов развёртывания gostforge.
# Подключается через dot-source: . "$PSScriptRoot\lib.ps1"
#
# Идентификаторы — на английском, комментарии — на русском (конвенция проекта).

$ErrorActionPreference = 'Stop'

# --- Логирование -------------------------------------------------------------
function Write-Info { param([string]$Msg) Write-Host "[*] $Msg" -ForegroundColor Blue }
function Write-Ok   { param([string]$Msg) Write-Host "[+] $Msg" -ForegroundColor Green }
function Write-Warn { param([string]$Msg) Write-Host "[!] $Msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$Msg) Write-Host "[x] $Msg" -ForegroundColor Red }

function Die {
    param([string]$Msg, [int]$Code = 1)
    Write-Err $Msg
    exit $Code
}

# Test-Command CMD — есть ли команда в PATH.
function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# --- Корень репозитория ------------------------------------------------------
# Скрипты лежат в <repo>\scripts, корень — на уровень выше.
function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

# --- Установка ПО (winget / choco) -------------------------------------------
# Install-WithWinget ID — установить пакет через winget.
function Install-WithWinget {
    param([string]$Id)
    & winget install --id $Id -e --source winget `
        --accept-package-agreements --accept-source-agreements
    return ($LASTEXITCODE -eq 0)
}

# Install-WithChoco PKG — установить пакет через Chocolatey.
function Install-WithChoco {
    param([string]$Pkg)
    & choco install $Pkg -y
    return ($LASTEXITCODE -eq 0)
}

# Install-Package — установить через доступный менеджер (winget приоритетнее).
function Install-Package {
    param([string]$WingetId, [string]$ChocoPkg)
    if (Test-Command winget) {
        if (Install-WithWinget $WingetId) { return $true }
        Write-Warn "winget не смог установить $WingetId — пробуем choco…"
    }
    if (Test-Command choco) {
        return (Install-WithChoco $ChocoPkg)
    }
    Write-Warn "Ни winget, ни choco не найдены."
    return $false
}

# Install-Git — установить git, если отсутствует.
function Install-Git {
    if (Test-Command git) { return }
    Write-Warn "git не найден — устанавливаем…"
    if (-not (Install-Package -WingetId 'Git.Git' -ChocoPkg 'git')) {
        Die "не удалось установить git автоматически. Скачайте: https://git-scm.com/download/win"
    }
    # Обновим PATH в текущей сессии (новые установки часто не видны до перезапуска).
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Test-Command git)) {
        Die "git установлен, но не виден в PATH. Перезапустите терминал и повторите."
    }
    Write-Ok "git установлен."
}

# Install-Docker — установить Docker Desktop, если отсутствует.
function Install-Docker {
    if (Test-Command docker) { return }
    Write-Warn "docker не найден — устанавливаем Docker Desktop…"
    if (-not (Install-Package -WingetId 'Docker.DockerDesktop' -ChocoPkg 'docker-desktop')) {
        Die "не удалось установить Docker Desktop. Скачайте: https://www.docker.com/products/docker-desktop/"
    }
    Write-Warn "Docker Desktop установлен. ЗАПУСТИТЕ Docker Desktop, дождитесь старта движка"
    Write-Warn "(может потребоваться включить WSL2 и перезагрузиться), затем повторите скрипт."
    Die "требуется ручной запуск Docker Desktop"
}

# Ensure-Dependencies [-WithGit] — проверка/автоустановка git/docker.
function Ensure-Dependencies {
    param([switch]$WithGit, [bool]$AllowInstall = $true)
    if ($AllowInstall) {
        if ($WithGit) { Install-Git }
        Install-Docker
    }
    else {
        Write-Info "Автоустановка отключена (-NoInstall) — только проверка наличия ПО."
        if ($WithGit -and -not (Test-Command git)) { Die "git не установлен (автоустановка отключена)" }
        if (-not (Test-Command docker)) { Die "docker не установлен (автоустановка отключена)" }
    }
}

# --- Docker / Compose --------------------------------------------------------
$script:ComposeCmd = $null

# Resolve-Compose — определяет форму compose-команды → $script:ComposeCmd (массив).
function Resolve-Compose {
    if (-not (Test-Command docker)) {
        Die "docker не найден в PATH. Установите Docker Desktop: https://www.docker.com/products/docker-desktop/"
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -eq 0) {
        $script:ComposeCmd = @('docker', 'compose')
        return
    }
    if (Test-Command docker-compose) {
        $script:ComposeCmd = @('docker-compose')
        return
    }
    Die "Docker Compose недоступен. Обновите Docker Desktop (включает Compose v2)."
}

# Invoke-Compose ARGS — обёртка над выбранной compose-командой.
# Простая функция (без param-блока): все аргументы, включая флаги вида -d,
# автоматически попадают в $args — иначе PowerShell пытается связать «-d»
# с параметром функции.
function Invoke-Compose {
    $exe = $script:ComposeCmd[0]
    $pre = @()
    if ($script:ComposeCmd.Count -gt 1) { $pre = $script:ComposeCmd[1..($script:ComposeCmd.Count - 1)] }
    & $exe @pre @args
}

# Ensure-DockerRunning — проверка, что демон Docker доступен.
function Ensure-DockerRunning {
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Die "демон Docker недоступен. Запустите Docker Desktop и дождитесь его готовности."
    }
}

# --- .env --------------------------------------------------------------------
function Ensure-EnvFile {
    param([string]$Root)
    $envPath = Join-Path $Root '.env'
    if (Test-Path $envPath) { return }
    $examplePath = Join-Path $Root '.env.example'
    if (Test-Path $examplePath) {
        Copy-Item $examplePath $envPath
        Write-Warn ".env не найден — создан из .env.example."
        Write-Warn "Проверьте $envPath: пустой GOSTFORGE_API_KEYS = REST API без авторизации."
    }
    else {
        Write-Warn ".env и .env.example отсутствуют — используются значения по умолчанию из docker-compose.yml."
    }
}

# Get-ServiceContainer SERVICE — имя контейнера сервиса (из docker-compose.yml).
function Get-ServiceContainer {
    param([string]$Service)
    switch ($Service) {
        'api' { 'gostforge-api' }
        'ui'  { 'gostforge-ui' }
        default { '' }
    }
}

# --- Ожидание healthcheck ----------------------------------------------------
function Wait-Healthy {
    param([string]$Container, [int]$TimeoutSec = 120)
    $waited = 0
    Write-Info "Ожидание готовности «$Container» (до $TimeoutSec с)…"
    while ($waited -lt $TimeoutSec) {
        $exists = & docker inspect $Container *> $null; $ok = ($LASTEXITCODE -eq 0)
        if (-not $ok) { Write-Err "Контейнер «$Container» не существует."; return $false }

        $state = (& docker inspect --format '{{.State.Status}}' $Container 2>$null)
        if ($state -eq 'exited' -or $state -eq 'dead') {
            Write-Err "Контейнер «$Container» завершился (status=$state)."; return $false
        }
        $status = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $Container 2>$null)
        switch ($status) {
            'healthy'   { Write-Ok "«$Container» — healthy."; return $true }
            'unhealthy' { Write-Err "«$Container» — unhealthy."; return $false }
            'none'      { if ($state -eq 'running') { Write-Ok "«$Container» — running (без healthcheck)."; return $true } }
        }
        Start-Sleep -Seconds 3
        $waited += 3
    }
    Write-Err "Таймаут ожидания «$Container» ($TimeoutSec с)."
    return $false
}

# Print-Summary SERVICES — итоговая сводка с адресами.
function Print-Summary {
    param([string[]]$Services)
    $root = Get-RepoRoot
    $bind = '127.0.0.1'; $uiBind = '127.0.0.1'
    $envPath = Join-Path $root '.env'
    if (Test-Path $envPath) {
        foreach ($line in Get-Content $envPath) {
            if ($line -match '^GOSTFORGE_BIND=(.+)$') { $bind = $Matches[1] }
            if ($line -match '^GOSTFORGE_UI_BIND=(.+)$') { $uiBind = $Matches[1] }
        }
    }
    Write-Host ''
    Write-Ok "Готово. Сервисы:"
    foreach ($svc in $Services) {
        switch ($svc) {
            'api' { Write-Host ("    REST API : http://{0}:8000  (проверка: curl http://{0}:8000/health)" -f $bind) }
            'ui'  { Write-Host ("    Web UI   : http://{0}:8501" -f $uiBind) }
        }
    }
    $cc = ($script:ComposeCmd -join ' ')
    Write-Host ''
    Write-Host "    Логи     : $cc logs -f [api|ui]"
    Write-Host "    Статус   : $cc ps"
    Write-Host "    Остановка: $cc down"
}
