#!/usr/bin/env bash
#
# deploy.sh — автоматическое развёртывание gostforge через Docker Compose.
#
# Собирает образы, поднимает сервисы (REST API и/или Streamlit UI),
# ждёт прохождения healthcheck'ов и печатает сводку с адресами.
#
# Примеры:
#   ./scripts/deploy.sh                 # api + ui (полное развёртывание)
#   ./scripts/deploy.sh --service api   # только REST API
#   ./scripts/deploy.sh --no-build      # без пересборки (используем образы как есть)
#   ./scripts/deploy.sh --pull          # сначала подтянуть свежие базовые образы
#
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

# --- Параметры по умолчанию --------------------------------------------------
SERVICES=(api ui)   # какие сервисы поднимать
DO_BUILD=1          # пересобирать образы
DO_PULL=0           # подтянуть базовые образы перед сборкой
HEALTH_TIMEOUT=120  # сек на healthcheck одного сервиса
ALLOW_INSTALL=1     # доустанавливать недостающее ПО (Docker/Compose)

usage() {
    cat <<'EOF'
Использование: deploy.sh [опции]

Опции:
  -s, --service NAME   Развернуть только указанный сервис (api | ui).
                       Можно повторять. По умолчанию — оба.
      --no-build       Не пересобирать образы (поднять существующие).
      --pull           Подтянуть свежие базовые образы перед сборкой.
      --no-install     Не доустанавливать ПО автоматически (только проверка).
      --timeout SEC    Таймаут ожидания healthcheck (по умолчанию 120).
  -h, --help           Показать эту справку.

Кроссплатформенно: Ubuntu/Linux и macOS. Для Windows используйте deploy.ps1.
Недостающие Docker / Docker Compose устанавливаются автоматически
(отключить — флагом --no-install). При первом запуске .env создаётся
из .env.example — заполните ключи!
EOF
}

# --- Разбор аргументов -------------------------------------------------------
PARSED_SERVICES=()
while [ $# -gt 0 ]; do
    case "$1" in
        -s | --service)
            [ $# -ge 2 ] || die "опция $1 требует значение (api|ui)"
            case "$2" in
                api | ui) PARSED_SERVICES+=("$2") ;;
                *) die "неизвестный сервис «$2» (допустимо: api, ui)" ;;
            esac
            shift 2
            ;;
        --no-build) DO_BUILD=0; shift ;;
        --pull) DO_PULL=1; shift ;;
        --no-install) ALLOW_INSTALL=0; shift ;;
        --timeout)
            [ $# -ge 2 ] || die "опция --timeout требует значение (секунды)"
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

export ALLOW_INSTALL
ensure_dependencies          # проверка/автоустановка Docker (+Compose ниже)
detect_compose
require_docker_running
ensure_env_file "$ROOT"

[ -f "$ROOT/docker-compose.yml" ] || die "docker-compose.yml не найден в $ROOT"

log_info "Корень проекта : $ROOT"
log_info "Compose        : ${COMPOSE_CMD[*]}"
log_info "Сервисы        : ${SERVICES[*]}"

# --- Сборка ------------------------------------------------------------------
if [ "$DO_PULL" -eq 1 ]; then
    log_info "Подтягиваем базовые образы…"
    compose pull --ignore-buildable "${SERVICES[@]}" 2>/dev/null || compose pull "${SERVICES[@]}" || true
fi

if [ "$DO_BUILD" -eq 1 ]; then
    log_info "Сборка образов…"
    compose build "${SERVICES[@]}"
else
    log_info "Сборка пропущена (--no-build)."
fi

# --- Запуск ------------------------------------------------------------------
log_info "Запуск сервисов…"
compose up -d "${SERVICES[@]}"

# --- Ожидание готовности -----------------------------------------------------
FAILED=0
for svc in "${SERVICES[@]}"; do
    container="$(service_container "$svc")"
    if ! wait_healthy "$container" "$HEALTH_TIMEOUT"; then
        FAILED=1
        log_err "Сервис «$svc» не вышел в healthy. Последние логи:"
        compose logs --tail 40 "$svc" || true
    fi
done

if [ "$FAILED" -ne 0 ]; then
    die "развёртывание завершилось с ошибками — см. логи выше."
fi

print_summary "${SERVICES[@]}"
