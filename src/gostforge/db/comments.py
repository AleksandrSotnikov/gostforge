# ruff: noqa: RUF001, RUF002, RUF003

"""Операции с таблицей comments (совместная работа руководитель ↔ студент).

Один submission → много комментариев в хронологическом порядке.
Автор хранится как строка — mapping строки в реального пользователя
делает вызывающая сторона (CLI берёт из env, REST принимает в
payload). Полноценной таблицы users пока нет — добавится при
переходе к multi-user сервису.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

CommentRole = Literal["student", "supervisor", "anonymous"]
_VALID_ROLES: frozenset[str] = frozenset({"student", "supervisor", "anonymous"})


@dataclass
class Comment:
    """Запись из таблицы ``comments``."""

    submission_id: int
    author: str
    role: str
    body: str
    created_at: str
    resolved: bool = False
    id: int | None = None


def add_comment(
    conn: sqlite3.Connection,
    *,
    submission_id: int,
    body: str,
    author: str = "",
    role: str = "anonymous",
    created_at: str | None = None,
) -> Comment:
    """Добавить комментарий к submission.

    Валидация:
      * ``body`` не должен быть пустым / только пробелами (ValueError);
      * ``role`` ограничена {student, supervisor, anonymous} (ValueError);
      * submission_id должен существовать (ValueError).

    ``created_at`` — ISO 8601 UTC; по умолчанию — текущее время.
    """
    if not body or not body.strip():
        raise ValueError("Текст комментария не может быть пустым")
    if role not in _VALID_ROLES:
        raise ValueError(
            f"role должна быть одной из {sorted(_VALID_ROLES)}, получено: {role!r}"
        )
    # Submission должен существовать — без FK CASCADE это даст IntegrityError
    # с не очень понятным текстом; делаем pre-check.
    exists = conn.execute(
        "SELECT 1 FROM submissions WHERE id = ?", (int(submission_id),)
    ).fetchone()
    if exists is None:
        raise ValueError(f"Submission #{submission_id} не существует")

    ts = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO comments (submission_id, author, role, body, resolved, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (int(submission_id), author, role, body.strip(), ts),
    )
    conn.commit()
    return Comment(
        id=int(cursor.lastrowid or 0),
        submission_id=int(submission_id),
        author=author,
        role=role,
        body=body.strip(),
        resolved=False,
        created_at=ts,
    )


def list_comments(
    conn: sqlite3.Connection,
    *,
    submission_id: int,
    include_resolved: bool = True,
) -> list[Comment]:
    """Все комментарии к submission в хронологическом порядке (старые первыми).

    ``include_resolved=False`` — показывать только незакрытые (для
    панели «что осталось обсудить»).
    """
    sql = "SELECT * FROM comments WHERE submission_id = ?"
    params: tuple[object, ...] = (int(submission_id),)
    if not include_resolved:
        sql += " AND resolved = 0"
    sql += " ORDER BY datetime(created_at), id"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_comment(r) for r in rows]


def get_comment(conn: sqlite3.Connection, comment_id: int) -> Comment | None:
    """Один комментарий по id или None."""
    row = conn.execute(
        "SELECT * FROM comments WHERE id = ?", (int(comment_id),)
    ).fetchone()
    return _row_to_comment(row) if row is not None else None


def resolve_comment(
    conn: sqlite3.Connection, comment_id: int, *, resolved: bool = True
) -> bool:
    """Пометить комментарий как resolved (или снять отметку).

    Возвращает True если запись существовала, иначе False.
    """
    cursor = conn.execute(
        "UPDATE comments SET resolved = ? WHERE id = ?",
        (1 if resolved else 0, int(comment_id)),
    )
    conn.commit()
    return (cursor.rowcount or 0) > 0


def delete_comment(conn: sqlite3.Connection, comment_id: int) -> bool:
    """Удалить комментарий. True если был, False если не было."""
    cursor = conn.execute(
        "DELETE FROM comments WHERE id = ?", (int(comment_id),)
    )
    conn.commit()
    return (cursor.rowcount or 0) > 0


def count_unresolved_comments(
    conn: sqlite3.Connection, submission_id: int
) -> int:
    """Сколько открытых (resolved=0) комментариев у submission."""
    row = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE submission_id = ? AND resolved = 0",
        (int(submission_id),),
    ).fetchone()
    return int(row[0]) if row else 0


def _row_to_comment(row: sqlite3.Row) -> Comment:
    return Comment(
        id=int(row["id"]),
        submission_id=int(row["submission_id"]),
        author=str(row["author"]),
        role=str(row["role"]),
        body=str(row["body"]),
        resolved=bool(row["resolved"]),
        created_at=str(row["created_at"]),
    )
