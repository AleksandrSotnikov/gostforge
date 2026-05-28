"""SQL-миграции схемы локальной БД.

Каждая миграция — кортеж ``(version, sql)``. ``apply_migrations`` идёт
по списку в порядке возрастания версий, применяет только новые
(version > current) и проставляет факт применения в schema_version.

Правила добавления новой миграции:

1. Никогда не редактировать существующие записи — только добавлять
   новые в конец списка.
2. SQL должен быть идемпотентным до уровня INSERT (CREATE IF NOT
   EXISTS, ALTER с проверкой) — потому что на старых установках
   текущая миграция может выполняться поверх частично-применённой
   схемы.
3. Каждая миграция в одной транзакции (sqlite3 это даёт по умолчанию,
   пока мы не делаем commit между шагами).
"""

from __future__ import annotations

import sqlite3

# Список миграций. Версия начинается с 1.
# Каждая SQL-строка может содержать несколько statement-ов; executescript
# их разберёт.
_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            error_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            info_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_submissions_created_at
            ON submissions(created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_submissions_filename
            ON submissions(filename);

        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            suggestion TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (submission_id)
                REFERENCES submissions(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_violations_submission_id
            ON violations(submission_id);

        CREATE INDEX IF NOT EXISTS idx_violations_code
            ON violations(code);
        """,
    ),
    (
        2,
        """
        -- Пользовательские профили (маркетплейс кафедр).
        -- profile_id — уникальный slug ("kafedra-prog-2026"),
        -- совпадает с полем id внутри YAML.
        CREATE TABLE IF NOT EXISTS custom_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT '1.0',
            yaml_content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            installed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_custom_profiles_profile_id
            ON custom_profiles(profile_id);
        """,
    ),
    (
        3,
        """
        -- Комментарии к submission-ам для совместной работы
        -- руководитель ↔ студент.
        --
        -- author — строка (имя/email/идентификатор). Полноценной
        -- таблицы users пока нет; mapping строки в пользователя
        -- делает вызывающая сторона (env GOSTFORGE_DEFAULT_AUTHOR
        -- в CLI, payload в REST).
        --
        -- role — простая enum-строка с CHECK-валидатором SQLite.
        -- 'anonymous' разрешён для случая, когда автор не задан.
        --
        -- resolved — флаг закрытия. Закрытые комментарии не
        -- скрываются, просто помечаются (студент видит, что
        -- руководитель счёл вопрос решённым).
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'anonymous'
                CHECK (role IN ('student', 'supervisor', 'anonymous')),
            body TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (submission_id)
                REFERENCES submissions(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_comments_submission_id
            ON comments(submission_id, created_at);

        CREATE INDEX IF NOT EXISTS idx_comments_resolved
            ON comments(resolved);
        """,
    ),
]


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Применить ещё не выполненные миграции. Возвращает число
    применённых.

    Создаёт ``schema_version``-таблицу, если её ещё нет; читает
    максимальную записанную версию; для каждой ``_MIGRATIONS[i]`` с
    ``version > current`` выполняет SQL и фиксирует факт.

    Безопасно вызывать многократно — повторный вызов будет noop.
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    current = int(row[0]) if row else 0

    applied = 0
    for version, sql in _MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        applied += 1
    conn.commit()
    return applied


def current_schema_version(conn: sqlite3.Connection) -> int:
    """Вернуть максимальную применённую версию схемы (0 если БД пуста)."""
    try:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        # Таблицы ещё нет — БД свежая, не инициализированная.
        return 0
