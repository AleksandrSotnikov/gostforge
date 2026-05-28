"""Локальный реестр пользовательских профилей (маркетплейс кафедр).

Профили хранятся как YAML-текст прямо в БД — это упрощает бэкап
(один SQLite-файл), перенос между машинами и распространение.

Установка идёт по двум путям:

* из локального файла (``install_profile_from_file``),
* из удалённого URL (``install_profile_from_url`` — отдельная функция
  в ``cli`` слое, тянет требования сети только при использовании).

Валидация делается через Pydantic-схему ``Profile`` ещё ДО записи в
БД — битый YAML отвергается с понятной ошибкой.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class CustomProfileRecord:
    """Запись из таблицы ``custom_profiles``."""

    profile_id: str
    name: str
    version: str
    yaml_content: str
    source: str
    installed_at: str
    id: int | None = None


def install_profile(
    conn: sqlite3.Connection,
    *,
    yaml_content: str,
    source: str = "",
    overwrite: bool = False,
) -> CustomProfileRecord:
    """Установить YAML-профиль в локальный реестр.

    Парсит YAML через Pydantic ``Profile``, проверяет схему,
    заполняет поля name/version/profile_id из самого YAML.

    ``overwrite=False`` (default) — при попытке установить профиль
    с тем же ``profile_id`` бросает ``ValueError``. Это защищает от
    случайной перезаписи через массовый импорт.

    ``source`` — произвольная метаинформация: URL, путь, описание
    источника. Хранится для трассировки «откуда установлен профиль».
    """
    import yaml as _yaml

    from gostforge.profile.schema import Profile

    try:
        data = _yaml.safe_load(yaml_content)
    except _yaml.YAMLError as exc:
        raise ValueError(f"Невалидный YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Профиль должен быть YAML-объектом, получено: {type(data).__name__}")

    try:
        profile = Profile(**data)
    except Exception as exc:
        raise ValueError(f"Профиль не прошёл валидацию схемы: {exc}") from exc

    existing = get_custom_profile(conn, profile.id)
    if existing is not None and not overwrite:
        raise ValueError(
            f"Профиль {profile.id!r} уже установлен. Используйте overwrite=True"
            " или сначала уберите его через uninstall."
        )

    ts = datetime.now(UTC).isoformat(timespec="seconds")
    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO custom_profiles
                (profile_id, name, version, yaml_content, source, installed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (profile.id, profile.name, profile.version, yaml_content, source, ts),
        )
        row_id = int(cursor.lastrowid or 0)
    else:
        conn.execute(
            """
            UPDATE custom_profiles
            SET name = ?, version = ?, yaml_content = ?,
                source = ?, installed_at = ?
            WHERE profile_id = ?
            """,
            (profile.name, profile.version, yaml_content, source, ts, profile.id),
        )
        row_id = int(existing.id or 0)
    conn.commit()

    return CustomProfileRecord(
        id=row_id,
        profile_id=profile.id,
        name=profile.name,
        version=profile.version,
        yaml_content=yaml_content,
        source=source,
        installed_at=ts,
    )


def uninstall_profile(conn: sqlite3.Connection, profile_id: str) -> bool:
    """Удалить custom-профиль по id. True если был, False если не было."""
    cursor = conn.execute("DELETE FROM custom_profiles WHERE profile_id = ?", (profile_id,))
    conn.commit()
    return (cursor.rowcount or 0) > 0


def get_custom_profile(conn: sqlite3.Connection, profile_id: str) -> CustomProfileRecord | None:
    """Получить custom-профиль по id или None."""
    row = conn.execute(
        "SELECT * FROM custom_profiles WHERE profile_id = ?", (profile_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_custom_profiles(conn: sqlite3.Connection) -> list[CustomProfileRecord]:
    """Все установленные пользовательские профили, по алфавиту id."""
    rows = conn.execute("SELECT * FROM custom_profiles ORDER BY profile_id").fetchall()
    return [_row_to_record(r) for r in rows]


def _row_to_record(row: sqlite3.Row) -> CustomProfileRecord:
    return CustomProfileRecord(
        id=int(row["id"]),
        profile_id=str(row["profile_id"]),
        name=str(row["name"]),
        version=str(row["version"]),
        yaml_content=str(row["yaml_content"]),
        source=str(row["source"]),
        installed_at=str(row["installed_at"]),
    )
