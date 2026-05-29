<#
.SYNOPSIS
    update.ps1 — установка обновлений gostforge из git и передеплой (Windows).

.DESCRIPTION
    Кроссплатформенный аналог update.sh для Windows / PowerShell.
    Проверяет обновления в удалённой ветке, делает бэкап SQLite-БД,
    подтягивает код, пересобирает контейнеры, ждёт healthcheck и при
    неудаче откатывается на прежний коммит. Недостающие git / Docker
    доустанавливаются автоматически (winget/choco).

.PARAMETER Branch
    Ветка для обновления. По умолчанию — текущая.

.PARAMETER Force
    Отбросить локальные изменения (git reset --hard origin/<branch>).

.PARAMETER NoBackup
    Не делать резервную копию БД.

.PARAMETER BackupDir
    Каталог для бэкапов (по умолчанию <repo>\backups).

.PARAMETER Service
    Пересоздавать только указанные сервисы (api, ui). По умолчанию — оба.

.PARAMETER NoInstall
    Не доустанавливать ПО автоматически.

.PARAMETER Timeout
    Таймаут ожидания healthcheck в секундах (по умолчанию 120).

.EXAMPLE
    .\scripts\update.ps1
.EXAMPLE
    .\scripts\update.ps1 -Branch main -Force
#>
[CmdletBinding()]
param(
    [string]$Branch = '',
    [switch]$Force,
    [switch]$NoBackup,
    [string]$BackupDir = '',
    [ValidateSet('api', 'ui')]
    [string[]]$Service = @('api', 'ui'),
    [switch]$NoInstall,
    [int]$Timeout = 120
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib.ps1"

$root = Get-RepoRoot
Set-Location $root
if (-not $BackupDir) { $BackupDir = Join-Path $root 'backups' }

Ensure-Dependencies -WithGit -AllowInstall (-not $NoInstall)
if (-not (Test-Path (Join-Path $root '.git'))) {
    Die "$root не является git-репозиторием — обновление из git невозможно"
}
Resolve-Compose
Ensure-DockerRunning

# Текущая ветка, если не задана.
if (-not $Branch) {
    $Branch = (& git rev-parse --abbrev-ref HEAD).Trim()
    if ($Branch -eq 'HEAD') { Die "репозиторий в detached HEAD — укажите ветку через -Branch" }
}
Write-Info "Ветка обновления: $Branch"

$oldCommit = (& git rev-parse HEAD).Trim()
Write-Info "Текущий коммит  : $($oldCommit.Substring(0,12))"

# --- Проверка наличия обновлений ---------------------------------------------
Write-Info "Проверяем удалённую ветку (git fetch)…"
& git fetch --prune origin $Branch
if ($LASTEXITCODE -ne 0) { Die "git fetch не удался" }

$remoteCommit = (& git rev-parse "origin/$Branch").Trim()
if (($oldCommit -eq $remoteCommit) -and (-not $Force)) {
    Write-Ok "Уже актуально (origin/$Branch == $($oldCommit.Substring(0,12))). Обновление не требуется."
    exit 0
}
Write-Info "Доступно обновление: $($oldCommit.Substring(0,12)) -> $($remoteCommit.Substring(0,12))"

# --- Резервная копия БД ------------------------------------------------------
if (-not $NoBackup) {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupFile = Join-Path $BackupDir "gostforge-db-$ts.db"
    $container = Get-ServiceContainer 'api'
    & docker inspect $container *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Info "Резервная копия БД -> $backupFile"
        Invoke-Compose cp "api:/var/lib/gostforge/gostforge.db" $backupFile 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Ok "Бэкап БД сохранён." }
        else {
            Write-Warn "БД ещё не создана или копирование не удалось — пропускаем бэкап."
            Remove-Item $backupFile -ErrorAction SilentlyContinue
        }
    }
    else { Write-Warn "Контейнер api не запущен — бэкап БД пропущен." }
}
else { Write-Info "Бэкап БД пропущен (-NoBackup)." }

# --- Обновление кода ---------------------------------------------------------
if ($Force) {
    Write-Warn "Принудительное обновление: локальные изменения будут отброшены."
    & git reset --hard "origin/$Branch"
    if ($LASTEXITCODE -ne 0) { Die "git reset --hard не удался" }
}
else {
    & git diff --quiet; $dirty1 = ($LASTEXITCODE -ne 0)
    & git diff --cached --quiet; $dirty2 = ($LASTEXITCODE -ne 0)
    if ($dirty1 -or $dirty2) {
        Die "есть незакоммиченные изменения. Закоммитьте/уберите их или используйте -Force."
    }
    & git checkout $Branch
    if ($LASTEXITCODE -ne 0) { Die "не удалось переключиться на ветку $Branch" }
    & git pull --ff-only origin $Branch
    if ($LASTEXITCODE -ne 0) { Die "git pull --ff-only не удался (история разошлась — используйте -Force)" }
}
$newCommit = (& git rev-parse HEAD).Trim()
Write-Ok "Код обновлён до $($newCommit.Substring(0,12))."

# rollback на прежний коммит.
function Invoke-Rollback {
    param([string]$Commit)
    Write-Warn "Откат на прежний коммит $($Commit.Substring(0,12))…"
    & git reset --hard $Commit
    if ($LASTEXITCODE -ne 0) { Write-Err "откат git не удался — требуется ручное вмешательство"; return }
    Write-Info "Пересборка прежней версии…"
    Invoke-Compose up -d --build @Service
    Write-Warn "Выполнен откат на $($Commit.Substring(0,12)). Проверьте: $($script:ComposeCmd -join ' ') ps"
}

Write-Info "Пересборка и пересоздание контейнеров…"
Invoke-Compose up -d --build @Service
if ($LASTEXITCODE -ne 0) {
    Write-Err "Сборка/запуск новой версии не удались."
    Invoke-Rollback -Commit $oldCommit
    Die "обновление прервано, выполнен откат."
}

$failed = $false
foreach ($svc in $Service) {
    $container = Get-ServiceContainer $svc
    if (-not (Wait-Healthy -Container $container -TimeoutSec $Timeout)) {
        $failed = $true
        Write-Err "Сервис «$svc» не прошёл healthcheck после обновления. Логи:"
        Invoke-Compose logs --tail 40 $svc
    }
}

if ($failed) {
    Write-Err "Новая версия нездорова — откатываемся."
    Invoke-Rollback -Commit $oldCommit
    Die "обновление откатано на $($oldCommit.Substring(0,12))."
}

Write-Ok "Обновление успешно: $($oldCommit.Substring(0,12)) -> $($newCommit.Substring(0,12))"
Print-Summary -Services $Service
