# shellcheck shell=bash
# Общие функции для скриптов развёртывания gostforge.
# Подключается через `source` в deploy.sh / update.sh.
#
# Идентификаторы — на английском, комментарии — на русском
# (конвенция проекта, см. CLAUDE.md).

# --- Цветной вывод -----------------------------------------------------------
# Цвета включаются только если stdout — терминал (иначе чистый текст в логах).
if [ -t 1 ]; then
    _C_RESET="\033[0m"
    _C_RED="\033[31m"
    _C_GREEN="\033[32m"
    _C_YELLOW="\033[33m"
    _C_BLUE="\033[34m"
else
    _C_RESET="" _C_RED="" _C_GREEN="" _C_YELLOW="" _C_BLUE=""
fi

log_info() { printf "${_C_BLUE}[*]${_C_RESET} %s\n" "$*"; }
log_ok() { printf "${_C_GREEN}[+]${_C_RESET} %s\n" "$*"; }
log_warn() { printf "${_C_YELLOW}[!]${_C_RESET} %s\n" "$*" >&2; }
log_err() { printf "${_C_RED}[x]${_C_RESET} %s\n" "$*" >&2; }

# die MSG [CODE] — напечатать ошибку и выйти.
die() {
    log_err "${1:-неизвестная ошибка}"
    exit "${2:-1}"
}

# have_cmd CMD — true, если команда есть в PATH.
have_cmd() { command -v "$1" >/dev/null 2>&1; }

# --- Определение ОС и менеджера пакетов --------------------------------------
# Заполняет OS_KIND (linux|macos) и для Linux — LINUX_PKG
# (apt|dnf|yum|pacman|zypper|apk|unknown).
detect_os() {
    local uname_s
    uname_s="$(uname -s 2>/dev/null || echo unknown)"
    case "$uname_s" in
        Linux) OS_KIND="linux" ;;
        Darwin) OS_KIND="macos" ;;
        *) OS_KIND="unknown" ;;
    esac

    LINUX_PKG="unknown"
    if [ "$OS_KIND" = "linux" ]; then
        if have_cmd apt-get; then LINUX_PKG="apt"
        elif have_cmd dnf; then LINUX_PKG="dnf"
        elif have_cmd yum; then LINUX_PKG="yum"
        elif have_cmd pacman; then LINUX_PKG="pacman"
        elif have_cmd zypper; then LINUX_PKG="zypper"
        elif have_cmd apk; then LINUX_PKG="apk"
        fi
    fi
}

# init_sudo — определяет, нужен ли sudo для установки (SUDO="" если root).
init_sudo() {
    if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        SUDO=""
    elif have_cmd sudo; then
        SUDO="sudo"
    else
        SUDO=""
        NO_SUDO=1
    fi
}

# pkg_install PKG... — установить пакеты текущим менеджером (Linux) или brew (macOS).
pkg_install() {
    case "$OS_KIND" in
        macos)
            brew install "$@"
            ;;
        linux)
            case "$LINUX_PKG" in
                apt) $SUDO apt-get update -y && $SUDO apt-get install -y "$@" ;;
                dnf) $SUDO dnf install -y "$@" ;;
                yum) $SUDO yum install -y "$@" ;;
                pacman) $SUDO pacman -Sy --noconfirm "$@" ;;
                zypper) $SUDO zypper install -y "$@" ;;
                apk) $SUDO apk add "$@" ;;
                *) return 1 ;;
            esac
            ;;
        *) return 1 ;;
    esac
}

# ensure_homebrew — на macOS гарантируем наличие Homebrew (нужен для установок).
ensure_homebrew() {
    [ "$OS_KIND" = "macos" ] || return 0
    if have_cmd brew; then return 0; fi
    log_warn "Homebrew не найден — устанавливаем (потребуется ввод пароля)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" ||
        die "не удалось установить Homebrew. Установите вручную: https://brew.sh"
    # Добавляем brew в PATH для текущей сессии (Apple Silicon / Intel).
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
}

# install_git — установить git, если отсутствует.
install_git() {
    have_cmd git && return 0
    log_warn "git не найден — устанавливаем…"
    case "$OS_KIND" in
        macos) ensure_homebrew; brew install git ;;
        linux)
            case "$LINUX_PKG" in
                apt | dnf | yum | pacman | zypper | apk) pkg_install git ;;
                *) die "неизвестный менеджер пакетов — установите git вручную" ;;
            esac
            ;;
        *) die "не удалось определить ОС для установки git" ;;
    esac
    have_cmd git || die "git так и не установился"
    log_ok "git установлен."
}

# install_docker — установить Docker Engine/Desktop, если отсутствует.
install_docker() {
    have_cmd docker && return 0
    log_warn "docker не найден — устанавливаем…"
    case "$OS_KIND" in
        macos)
            ensure_homebrew
            log_info "Ставим Docker Desktop (cask)…"
            brew install --cask docker ||
                die "не удалось установить Docker Desktop. Скачайте вручную: https://www.docker.com/products/docker-desktop/"
            log_warn "Docker Desktop установлен. ЗАПУСТИТЕ приложение Docker и дождитесь старта движка, затем повторите."
            die "требуется ручной запуск Docker Desktop"
            ;;
        linux)
            if [ "$LINUX_PKG" = "apt" ] || [ "$LINUX_PKG" = "dnf" ] || [ "$LINUX_PKG" = "yum" ]; then
                # Официальный convenience-скрипт Docker ставит engine + compose-plugin.
                log_info "Используем официальный скрипт get.docker.com…"
                if have_cmd curl; then
                    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
                elif have_cmd wget; then
                    wget -qO /tmp/get-docker.sh https://get.docker.com
                else
                    pkg_install curl || die "нужен curl или wget для установки Docker"
                    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
                fi
                $SUDO sh /tmp/get-docker.sh || die "установка Docker через get.docker.com не удалась"
                rm -f /tmp/get-docker.sh
                # Добавляем текущего пользователя в группу docker (вступит в силу после релогина).
                if [ "${EUID:-$(id -u)}" -ne 0 ] && have_cmd usermod; then
                    $SUDO usermod -aG docker "$USER" || true
                    log_warn "Пользователь добавлен в группу docker — перелогиньтесь, если docker требует sudo."
                fi
            else
                # Прочие дистрибутивы — пакет из репозитория (имя варьируется).
                pkg_install docker || pkg_install docker.io || pkg_install moby-engine ||
                    die "установите Docker вручную для вашего дистрибутива: https://docs.docker.com/engine/install/"
                # Запустим и включим сервис, если есть systemd.
                if have_cmd systemctl; then
                    $SUDO systemctl enable --now docker || true
                fi
            fi
            ;;
        *) die "не удалось определить ОС для установки Docker" ;;
    esac
    have_cmd docker || die "docker так и не установился"
    log_ok "Docker установлен."
}

# ensure_dependencies [--with-git] — проверить и (при ALLOW_INSTALL=1) доустановить
# git/docker/compose. Без ALLOW_INSTALL только сообщает об отсутствии.
ensure_dependencies() {
    local need_git=0
    [ "${1:-}" = "--with-git" ] && need_git=1

    detect_os
    init_sudo

    if [ "${ALLOW_INSTALL:-1}" -eq 1 ]; then
        if [ "${NO_SUDO:-0}" -eq 1 ] && [ "$OS_KIND" = "linux" ]; then
            log_warn "Нет root и нет sudo — автоустановка ПО невозможна, только проверка."
        else
            [ "$need_git" -eq 1 ] && install_git
            install_docker
        fi
    else
        log_info "Автоустановка отключена (--no-install) — только проверка наличия ПО."
        if [ "$need_git" -eq 1 ] && ! have_cmd git; then
            die "git не установлен (автоустановка отключена)"
        fi
        if ! have_cmd docker; then
            die "docker не установлен (автоустановка отключена)"
        fi
    fi
}

# --- Корень репозитория ------------------------------------------------------
# Скрипты лежат в <repo>/scripts, поэтому корень — на уровень выше.
repo_root() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$script_dir/.." && pwd
}

# --- Docker / Compose --------------------------------------------------------
# Определяем доступную форму compose-команды: «docker compose» (v2) либо
# legacy «docker-compose». Результат кладётся в массив COMPOSE_CMD.
# Если плагина нет и ALLOW_INSTALL=1 — пробуем доустановить (apt/dnf/brew).
detect_compose() {
    if ! have_cmd docker; then
        die "docker не найден в PATH. Установите Docker Engine: https://docs.docker.com/engine/install/"
    fi
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
        return 0
    elif have_cmd docker-compose; then
        COMPOSE_CMD=(docker-compose)
        return 0
    fi

    # Плагина нет — пробуем установить (compose обычно идёт с Docker Desktop
    # и с convenience-скриптом, но на чистом apt-докере может отсутствовать).
    if [ "${ALLOW_INSTALL:-1}" -eq 1 ]; then
        log_warn "Docker Compose не найден — пробуем установить плагин…"
        detect_os
        init_sudo
        case "$LINUX_PKG" in
            apt) pkg_install docker-compose-plugin || true ;;
            dnf | yum) pkg_install docker-compose-plugin || true ;;
            *) : ;;
        esac
        if docker compose version >/dev/null 2>&1; then
            COMPOSE_CMD=(docker compose)
            log_ok "Docker Compose установлен."
            return 0
        fi
    fi
    die "ни «docker compose», ни «docker-compose» не доступны. Установите Docker Compose v2: https://docs.docker.com/compose/install/"
}

# compose ARGS... — обёртка над выбранной compose-командой.
compose() { "${COMPOSE_CMD[@]}" "$@"; }

# --- Проверка демона Docker --------------------------------------------------
require_docker_running() {
    if ! docker info >/dev/null 2>&1; then
        die "демон Docker недоступен. Запущен ли он и есть ли у пользователя права (группа docker)?"
    fi
}

# --- .env --------------------------------------------------------------------
# Гарантируем наличие .env: если нет — копируем из .env.example и
# предупреждаем, что значения нужно заполнить.
ensure_env_file() {
    local root="$1"
    if [ -f "$root/.env" ]; then
        return 0
    fi
    if [ -f "$root/.env.example" ]; then
        cp "$root/.env.example" "$root/.env"
        log_warn ".env не найден — создан из .env.example."
        log_warn "Проверьте $root/.env: пустой GOSTFORGE_API_KEYS = REST API без авторизации."
    else
        log_warn ".env и .env.example отсутствуют — используются значения по умолчанию из docker-compose.yml."
    fi
}

# service_container SERVICE — имя контейнера для сервиса (из docker-compose.yml).
service_container() {
    case "$1" in
        api) echo "gostforge-api" ;;
        ui) echo "gostforge-ui" ;;
        *) echo "" ;;
    esac
}

# --- Ожидание healthcheck ----------------------------------------------------
# wait_healthy CONTAINER TIMEOUT_SEC — ждём, пока контейнер не станет
# healthy. Возвращает 0 при успехе, 1 при таймауте/падении.
wait_healthy() {
    local container="$1" timeout="${2:-90}" waited=0 status
    log_info "Ожидание готовности «$container» (до ${timeout}с)…"
    while [ "$waited" -lt "$timeout" ]; do
        if ! docker inspect "$container" >/dev/null 2>&1; then
            log_err "Контейнер «$container» не существует."
            return 1
        fi
        # Статус: running/exited/…
        local state
        state="$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")"
        if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
            log_err "Контейнер «$container» завершился (status=$state)."
            return 1
        fi
        # Health: healthy/starting/unhealthy либо пусто (нет healthcheck).
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || echo "none")"
        case "$status" in
            healthy)
                log_ok "«$container» — healthy."
                return 0
                ;;
            none)
                # Healthcheck не определён — считаем готовым по running.
                if [ "$state" = "running" ]; then
                    log_ok "«$container» — running (без healthcheck)."
                    return 0
                fi
                ;;
            unhealthy)
                log_err "«$container» — unhealthy."
                return 1
                ;;
        esac
        sleep 3
        waited=$((waited + 3))
    done
    log_err "Таймаут ожидания «$container» (${timeout}с). Текущий health: ${status:-unknown}."
    return 1
}

# print_summary SERVICES... — итоговая сводка с адресами и подсказками.
print_summary() {
    local root bind ui_bind
    root="$(repo_root)"
    # Адреса берём из .env (если есть), иначе дефолты из compose.
    bind="127.0.0.1"
    ui_bind="127.0.0.1"
    if [ -f "$root/.env" ]; then
        bind="$(grep -E '^GOSTFORGE_BIND=' "$root/.env" | tail -1 | cut -d= -f2-)"
        ui_bind="$(grep -E '^GOSTFORGE_UI_BIND=' "$root/.env" | tail -1 | cut -d= -f2-)"
        bind="${bind:-127.0.0.1}"
        ui_bind="${ui_bind:-127.0.0.1}"
    fi
    echo
    log_ok "Готово. Сервисы:"
    local svc
    for svc in "$@"; do
        case "$svc" in
            api) printf "    REST API : http://%s:8000  (проверка: curl http://%s:8000/health)\n" "$bind" "$bind" ;;
            ui) printf "    Web UI   : http://%s:8501\n" "$ui_bind" ;;
        esac
    done
    echo
    printf "    Логи     : %s logs -f [api|ui]\n" "${COMPOSE_CMD[*]}"
    printf "    Статус   : %s ps\n" "${COMPOSE_CMD[*]}"
    printf "    Остановка: %s down\n" "${COMPOSE_CMD[*]}"
}
