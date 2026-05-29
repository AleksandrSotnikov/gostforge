# Скрипты развёртывания и обновления

Обёртки над Docker-инфраструктурой проекта (`Dockerfile`,
`Dockerfile.ui`, `docker-compose.yml`) для развёртывания gostforge
и установки обновлений из git.

Кроссплатформенно:

| ОС | Скрипты | Менеджер для автоустановки ПО |
|---|---|---|
| **Ubuntu / Linux** | `deploy.sh`, `update.sh` | apt / dnf / yum / pacman / zypper / apk |
| **macOS** | `deploy.sh`, `update.sh` | Homebrew (ставится автоматически) |
| **Windows** | `deploy.ps1`, `update.ps1` | winget / Chocolatey |

> На Windows скрипты `.sh` тоже работают, если запускать их из **WSL** или
> **Git Bash**; нативный путь — PowerShell-версии `.ps1`.

## Автоустановка недостающего ПО

Скрипты сами доустанавливают **git**, **Docker** и **Docker Compose**,
если их нет:

- **Ubuntu/Debian, Fedora, RHEL** — официальный скрипт
  [get.docker.com](https://get.docker.com) (engine + compose-plugin);
  git — через системный менеджер пакетов.
- **macOS** — Docker Desktop (`brew install --cask docker`); при первом
  запуске Docker Desktop нужно запустить вручную и дождаться старта движка.
- **Windows** — Docker Desktop (`winget install Docker.DockerDesktop`);
  требуется WSL2 и ручной запуск Docker Desktop.

Отключить автоустановку: флаг `--no-install` (bash) / `-NoInstall`
(PowerShell) — тогда скрипт только проверит наличие ПО и завершится с
ошибкой, если чего-то не хватает.

> Установка Docker требует прав root/sudo (Linux) или администратора
> (Windows). На Linux без root и без sudo автоустановка невозможна —
> поставьте Docker заранее.

## Развёртывание

```bash
# Linux / macOS
./scripts/deploy.sh                 # api + ui, со сборкой образов
./scripts/deploy.sh --service api   # только REST API
./scripts/deploy.sh --no-build      # поднять уже собранные образы
./scripts/deploy.sh --no-install    # не доустанавливать ПО
```

```powershell
# Windows (PowerShell)
.\scripts\deploy.ps1
.\scripts\deploy.ps1 -Service api -NoInstall
```

Что делает `deploy`:

1. Проверяет/доустанавливает Docker и Compose.
2. Создаёт `.env` из `.env.example`, если его нет (заполните ключи!).
3. Собирает образы и поднимает сервисы (`docker compose up -d`).
4. Ждёт прохождения healthcheck'ов.
5. Печатает адреса: REST API на `:8000`, Web UI на `:8501`.

## Обновление из git

```bash
# Linux / macOS
./scripts/update.sh                 # обновить текущую ветку (ff-only)
./scripts/update.sh --branch main   # из ветки main
./scripts/update.sh --force         # отбросить локальные правки (reset --hard)
./scripts/update.sh --no-backup     # без бэкапа БД
```

```powershell
# Windows
.\scripts\update.ps1 -Branch main
.\scripts\update.ps1 -Force
```

Что делает `update`:

1. Проверяет/доустанавливает git, Docker, Compose.
2. `git fetch` — есть ли новые коммиты. Если нет — выходит.
3. Делает резервную копию SQLite-БД истории в `backups/`
   (через `docker compose cp`; каталог в `.gitignore`).
4. Подтягивает код (`git pull --ff-only`, либо `reset --hard` при `--force`).
5. Пересобирает образы и пересоздаёт контейнеры.
6. Ждёт healthcheck. **При неудаче — автоматический откат** кода на
   прежний коммит и пересборка старой версии.

## Автообновление по расписанию

**Linux (cron):** обновлять каждую ночь в 03:00, лог в файл:

```cron
0 3 * * * cd /opt/gostforge && ./scripts/update.sh >> /var/log/gostforge-update.log 2>&1
```

**Linux (systemd timer):** см. `update.service` + `update.timer`
(создайте по образцу из cron-команды выше).

**Windows (Task Scheduler):**

```powershell
$action  = New-ScheduledTaskAction -Execute 'pwsh' `
    -Argument '-File C:\gostforge\scripts\update.ps1' -WorkingDirectory 'C:\gostforge'
$trigger = New-ScheduledTaskTrigger -Daily -At 3am
Register-ScheduledTask -TaskName 'gostforge-update' -Action $action -Trigger $trigger
```

## Опции

| bash | PowerShell | Назначение |
|---|---|---|
| `-s, --service api\|ui` | `-Service api,ui` | какие сервисы (по умолчанию оба) |
| `--no-build` | `-NoBuild` | не пересобирать образы (только deploy) |
| `--pull` | `-Pull` | подтянуть базовые образы (только deploy) |
| `--branch NAME` | `-Branch NAME` | ветка git (только update) |
| `--force` | `-Force` | reset --hard (только update) |
| `--no-backup` | `-NoBackup` | без бэкапа БД (только update) |
| `--backup-dir DIR` | `-BackupDir DIR` | каталог бэкапов (только update) |
| `--no-install` | `-NoInstall` | не доустанавливать ПО |
| `--timeout SEC` | `-Timeout SEC` | таймаут healthcheck (по умолчанию 120) |
| `-h, --help` | `Get-Help .\deploy.ps1` | справка |

Подробности про переменные окружения (`GOSTFORGE_API_KEYS`,
`GOSTFORGE_CORS_ORIGINS`, …) — в `.env.example` и `docs/api.md`.
