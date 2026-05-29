#!/usr/bin/env bash
#
# update.sh — установка обновлений gostforge из git и безопасный передеплой.
#
# Что делает:
#   1. Проверяет наличие обновлений в удалённой ветке (git fetch).
#   2. Делает резервную копию SQLite-БД истории (из volume/контейнера).
#   3. Подтягивает новый код (git pull --ff-only либо reset --hard при --force).
#   4. Пересобирает образы и пересоздаёт контейнеры.
#   5. Ждёт healthcheck. При неудаче — откатывает код на прежний коммит,
#      пересобирает и поднимает старую версию (rollback).
#
# Подходит для запуска по cron / systemd-timer (см. scripts/README.md).
#
# Примеры:
#   ./scripts/update.sh                  # обновить текущую ветку (ff-only)
#   ./scripts/update.sh --branch main    # обновить из ветки main
#   ./scripts/update.sh --force          # отбросить локальные правки (reset --hard)
#   ./scripts/update.sh --no-backup      # без бэкапа БД
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

# --- Параметры по умолчанию --------------------------------------------------
BRANCH=""           # пусто => текущая ветка
FORCE=0             # git reset --hard вместо ff-only pull
DO_BACKUP=1         # бэкап БД перед обновлением
SERVICES=(api ui)
HEALTH_TIMEOUT=120
BACKUP_DIR=""       # по умолчанию <repo>/backups
ALLOW_INSTALL=1     # доустанавливать недостающее ПО (git/Docker/Compose)

usage() {
    cat <<'EOF'
Использование: update.sh [опции]

Опции:
  -b, --branch NAME    Ветка для обновления (по умолчанию — текущая).
      --force          Отбросить локальные изменения (git reset --hard origin/<branch>).
      --no-backup      Не делать резервную копию БД перед обновлением.
      --backup-dir DIR Каталог для бэкапов (по умолчанию <repo>/backups).
  -s, --service NAME   Пересоздавать только указанный сервис (api|ui). Можно повторять.
      --no-install     Не доустанавливать ПО автоматически (только проверка).
      --timeout SEC    Таймаут ожидания healthcheck (по умолчанию 120).
  -h, --help           Показать справку.

Кроссплатформенно: Ubuntu/Linux и macOS. Для Windows используйте update.ps1.
Недостающие git / Docker / Compose устанавливаются автоматически
(отключить — флагом --no-install). При неудачном healthcheck код
автоматически откатывается на прежний коммит.
EOF
}

# --- Разбор аргументов -------------------------------------------------------
PARSED_SERVICES=()
while [ $# -gt 0 ]; do
    case "$1" in
        -b | --branch)
            [ $# -ge 2 ] || die "опция $1 требует имя ветки"
            BRANCH="$2"; shift 2
            ;;
        --force) FORCE=1; shift ;;
        --no-backup) DO_BACKUP=0; shift ;;
        --backup-dir)
            [ $# -ge 2 ] || die "опция --backup-dir требует путь"
            BACKUP_DIR="$2"; shift 2
            ;;
        -s | --service)
            [ $# -ge 2 ] || die "опция $1 требует значение (api|ui)"
            case "$2" in
                api | ui) PARSED_SERVICES+=("$2") ;;
                *) die "неизвестный сервис «$2»" ;;
            esac
            shift 2
            ;;
        --no-install) ALLOW_INSTALL=0; shift ;;
        --timeout)
            [ $# -ge 2 ] || die "опция --timeout требует значение"
            HEALTH_TIMEOUT="$2"; shift 2
            ;;
        -h | --help) usage; exit 0 ;;
        *) die "неизвестная опция «$1» (см. --help)" ;;
    esac
done
if [ "${#PARSED_SERVICES[@]}" -gt 0 ]; then
    SERVICES=("${PARSED_SERVICES[@]}")
fi

# --- Подготовка --------------------------------------------------------------
ROOT="$(repo_root)"
cd "$ROOT"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"

export ALLOW_INSTALL
ensure_dependencies --with-git   # проверка/автоустановка git + Docker
[ -d "$ROOT/.git" ] || die "$ROOT не является git-репозиторием — обновление из git невозможно"
detect_compose
require_docker_running

# Определяем текущую ветку, если не задана явно.
if [ -z "$BRANCH" ]; then
    BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    [ "$BRANCH" != "HEAD" ] || die "репозиторий в detached HEAD — укажите ветку через --branch"
fi
log_info "Ветка обновления: $BRANCH"

# Запоминаем текущий коммит — понадобится для отката.
OLD_COMMIT="$(git rev-parse HEAD)"
log_info "Текущий коммит  : ${OLD_COMMIT:0:12}"

# --- Проверка наличия обновлений ---------------------------------------------
log_info "Проверяем удалённую ветку (git fetch)…"
git fetch --prune origin "$BRANCH" || die "git fetch не удался"

REMOTE_COMMIT="$(git rev-parse "origin/$BRANCH")"
if [ "$OLD_COMMIT" = "$REMOTE_COMMIT" ] && [ "$FORCE" -eq 0 ]; then
    log_ok "Уже актуально (origin/$BRANCH == ${OLD_COMMIT:0:12}). Обновление не требуется."
    exit 0
fi
log_info "Доступно обновление: ${OLD_COMMIT:0:12} → ${REMOTE_COMMIT:0:12}"

# --- Резервная копия БД ------------------------------------------------------
if [ "$DO_BACKUP" -eq 1 ]; then
    mkdir -p "$BACKUP_DIR"
    ts="$(date +%Y%m%d-%H%M%S)"
    backup_file="$BACKUP_DIR/gostforge-db-$ts.db"
    container="$(service_container api)"
    if docker inspect "$container" >/dev/null 2>&1; then
        log_info "Резервная копия БД → $backup_file"
        # docker compose cp копирует файл из контейнера на хост.
        if compose cp "api:/var/lib/gostforge/gostforge.db" "$backup_file" 2>/dev/null; then
            log_ok "Бэкап БД сохранён ($(du -h "$backup_file" 2>/dev/null | cut -f1))."
        else
            log_warn "БД ещё не создана или копирование не удалось — пропускаем бэкап."
            rm -f "$backup_file" 2>/dev/null || true
        fi
    else
        log_warn "Контейнер api не запущен — бэкап БД пропущен."
    fi
else
    log_info "Бэкап БД пропущен (--no-backup)."
fi

# --- Обновление кода ---------------------------------------------------------
if [ "$FORCE" -eq 1 ]; then
    log_warn "Принудительное обновление: локальные изменения будут отброшены."
    git reset --hard "origin/$BRANCH" || die "git reset --hard не удался"
else
    # Чистое ли дерево? Иначе ff-only pull упадёт — подсказываем --force.
    if ! git diff --quiet || ! git diff --cached --quiet; then
        die "есть незакоммиченные изменения. Закоммитьте/уберите их или используйте --force."
    fi
    git checkout "$BRANCH" 2>/dev/null || die "не удалось переключиться на ветку $BRANCH"
    git pull --ff-only origin "$BRANCH" || die "git pull --ff-only не удался (история разошлась — используйте --force)"
fi
NEW_COMMIT="$(git rev-parse HEAD)"
log_ok "Код обновлён до ${NEW_COMMIT:0:12}."

# --- Пересборка и пересоздание контейнеров -----------------------------------
# rollback_to COMMIT — откат кода и передеплой прежней версии.
rollback_to() {
    local commit="$1"
    log_warn "Откат на прежний коммит ${commit:0:12}…"
    git reset --hard "$commit" || { log_err "откат git не удался — требуется ручное вмешательство"; return 1; }
    log_info "Пересборка прежней версии…"
    compose up -d --build "${SERVICES[@]}" || { log_err "не удалось поднять прежнюю версию"; return 1; }
    log_warn "Выполнен откат на ${commit:0:12}. Проверьте состояние: ${COMPOSE_CMD[*]} ps"
}

log_info "Пересборка и пересоздание контейнеров…"
if ! compose up -d --build "${SERVICES[@]}"; then
    log_err "Сборка/запуск новой версии не удались."
    rollback_to "$OLD_COMMIT" || true
    die "обновление прервано, выполнен откат."
fi

# --- Проверка здоровья + откат при неудаче -----------------------------------
FAILED=0
for svc in "${SERVICES[@]}"; do
    container="$(service_container "$svc")"
    if ! wait_healthy "$container" "$HEALTH_TIMEOUT"; then
        FAILED=1
        log_err "Сервис «$svc» не прошёл healthcheck после обновления. Логи:"
        compose logs --tail 40 "$svc" || true
    fi
done

if [ "$FAILED" -ne 0 ]; then
    log_err "Новая версия нездорова — откатываемся."
    rollback_to "$OLD_COMMIT" || true
    die "обновление откатано на ${OLD_COMMIT:0:12}."
fi

log_ok "Обновление успешно: ${OLD_COMMIT:0:12} → ${NEW_COMMIT:0:12}"
print_summary "${SERVICES[@]}"
