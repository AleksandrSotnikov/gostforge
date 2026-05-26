# ruff: noqa: RUF002, RUF003

"""Локальная SQLite-БД gostforge.

Хранение опционально: основной функционал (check / fix / annotate /
builder) работает без БД. БД нужна для:

* истории проверок (submissions) — трекинг прогресса студента,
* пользовательских профилей в локальном реестре,
* комментариев руководителя в командной работе (future).

Путь БД — ``~/.gostforge/gostforge.db`` по умолчанию, переопределяется
env ``GOSTFORGE_DB_PATH``. Каталог создаётся автоматически. Схема
поднимается на первое открытие соединения (auto-migrate); пользователю
не нужно запускать ``init``.

Подход к миграциям — простой ``schema_version``-счётчик + список SQL.
SQLAlchemy / Alembic не используем: для текущего объёма (3-5 таблиц,
INSERT/SELECT без сложных JOIN) stdlib ``sqlite3`` достаточно.
"""

from __future__ import annotations

from .connection import default_db_path, get_connection
from .custom_profiles import (
    CustomProfileRecord,
    get_custom_profile,
    install_profile,
    list_custom_profiles,
    uninstall_profile,
)
from .schema import Submission, ViolationRecord
from .submissions import (
    get_submission,
    list_submissions,
    record_submission,
)

__all__ = [
    "CustomProfileRecord",
    "Submission",
    "ViolationRecord",
    "default_db_path",
    "get_connection",
    "get_custom_profile",
    "get_submission",
    "install_profile",
    "list_custom_profiles",
    "list_submissions",
    "record_submission",
    "uninstall_profile",
]
