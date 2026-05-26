# ruff: noqa: RUF001, RUF002, RUF003

"""Открытие соединения с локальной SQLite-БД с auto-init схемы.

Соглашения:

* Путь БД из env ``GOSTFORGE_DB_PATH`` или дефолтный
  ``~/.gostforge/gostforge.db``.
* Каталог создаётся автоматически.
* На каждом открытом соединении включаются:
  - PRAGMA foreign_keys=ON — иначе CASCADE-удаления не работают,
  - PRAGMA journal_mode=WAL — лучшая параллельность read/write,
  - row_factory=sqlite3.Row — обращение к колонкам по имени.
* При первом открытии (или после bump-версии схемы) автоматически
  выполняются миграции.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .migrations import apply_migrations


def default_db_path() -> Path:
    """Дефолтный путь к БД: ``~/.gostforge/gostforge.db``.

    Можно переопределить env-переменной ``GOSTFORGE_DB_PATH`` — это
    удобно для тестов (в tmp_path) и для нестандартных установок
    (другой volume в Docker).
    """
    env_path = os.environ.get("GOSTFORGE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path.home() / ".gostforge" / "gostforge.db"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Открыть соединение, создать каталог и применить миграции.

    На каждом вызове возвращается новое соединение — sqlite3 thread-local,
    реюз через глобал не безопасен. Caller обязан закрыть его (или
    использовать ``with`` — sqlite3.Connection поддерживает контекст-
    менеджер, который ``commit()`` на выходе).
    """
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # PRAGMA нужно установить ДО первой записи; их порядок не критичен.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    apply_migrations(conn)
    return conn
