#!/bin/bash
# SessionStart-хук для Claude Code on the web.
#
# Задача: поднять dev-окружение так, чтобы `python -m pytest`, `ruff` и
# `mypy src` работали из коробки, как описано в CLAUDE.md.
#
# Нюанс облачного образа: в PATH впереди стоит отдельный user-site
# (/root/.local/bin), чей mypy/pytest НЕ видит зависимости проекта,
# установленные в проектный интерпретатор (/usr/local). Из-за этого
# `mypy src` выдавал сотни ложных import-not-found/untyped-decorator.
# Хук ставит dev-зависимости в проектный python и поднимает каталог его
# консольных скриптов в начало PATH на сессию.
set -euo pipefail

# Только в удалённом окружении (Claude Code on the web). Локально хук
# ничего не делает, чтобы не трогать окружение разработчика.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Editable-установка проекта со всеми dev-зависимостями (pytest, ruff,
# mypy, type-стабы, streamlit/fastapi для тестов web/api). Идемпотентно.
python -m pip install -e ".[dev]"

# Каталог консольных скриптов проектного интерпретатора (обычно
# /usr/local/bin). Его mypy/pytest/ruff видят зависимости проекта —
# ставим его первым в PATH на всю сессию.
PY_SCRIPTS="$(python -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"
echo "export PATH=\"$PY_SCRIPTS:\$PATH\"" >> "$CLAUDE_ENV_FILE"

# Подстраховка для pytest: editable-пакет обычно подхватывается через
# .pth, но в части окружений этого не происходит — добавляем src.
echo "export PYTHONPATH=\"$CLAUDE_PROJECT_DIR/src\"" >> "$CLAUDE_ENV_FILE"
