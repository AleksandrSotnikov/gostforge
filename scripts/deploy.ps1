<#
.SYNOPSIS
    deploy.ps1 — автоматическое развёртывание gostforge через Docker Compose (Windows).

.DESCRIPTION
    Кроссплатформенный аналог deploy.sh для Windows / PowerShell.
    Доустанавливает недостающие Docker Desktop / Compose (winget/choco),
    собирает образы, поднимает сервисы (REST API и/или Streamlit UI),
    ждёт healthcheck и печатает сводку.

.PARAMETER Service
    Какие сервисы поднимать: api, ui. По умолчанию — оба.

.PARAMETER NoBuild
    Не пересобирать образы (поднять существующие).

.PARAMETER Pull
    Подтянуть свежие базовые образы перед сборкой.

.PARAMETER NoInstall
    Не доустанавливать ПО автоматически (только проверка наличия).

.PARAMETER Timeout
    Таймаут ожидания healthcheck в секундах (по умолчанию 120).

.EXAMPLE
    .\scripts\deploy.ps1
.EXAMPLE
    .\scripts\deploy.ps1 -Service api -NoInstall
#>
[CmdletBinding()]
param(
    [ValidateSet('api', 'ui')]
    [string[]]$Service = @('api', 'ui'),
    [switch]$NoBuild,
    [switch]$Pull,
    [switch]$NoInstall,
    [int]$Timeout = 120
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\lib.ps1"

$root = Get-RepoRoot
Set-Location $root

Ensure-Dependencies -AllowInstall (-not $NoInstall)
Resolve-Compose
Ensure-DockerRunning
Ensure-EnvFile $root

if (-not (Test-Path (Join-Path $root 'docker-compose.yml'))) {
    Die "docker-compose.yml не найден в $root"
}

Write-Info "Корень проекта : $root"
Write-Info "Compose        : $($script:ComposeCmd -join ' ')"
Write-Info "Сервисы        : $($Service -join ', ')"

if ($Pull) {
    Write-Info "Подтягиваем базовые образы…"
    Invoke-Compose pull @Service 2>$null
}

if (-not $NoBuild) {
    Write-Info "Сборка образов…"
    Invoke-Compose build @Service
    if ($LASTEXITCODE -ne 0) { Die "сборка образов не удалась" }
}
else {
    Write-Info "Сборка пропущена (-NoBuild)."
}

Write-Info "Запуск сервисов…"
Invoke-Compose up -d @Service
if ($LASTEXITCODE -ne 0) { Die "не удалось поднять сервисы" }

$failed = $false
foreach ($svc in $Service) {
    $container = Get-ServiceContainer $svc
    if (-not (Wait-Healthy -Container $container -TimeoutSec $Timeout)) {
        $failed = $true
        Write-Err "Сервис «$svc» не вышел в healthy. Последние логи:"
        Invoke-Compose logs --tail 40 $svc
    }
}

if ($failed) { Die "развёртывание завершилось с ошибками — см. логи выше." }

Print-Summary -Services $Service
