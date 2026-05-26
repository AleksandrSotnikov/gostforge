# ruff: noqa: RUF001, RUF002, RUF003

"""Операции с таблицей submissions: запись, выборка, удаление.

Submission — это снимок «файл X проверен профилем Y в момент Z,
найдено N нарушений». Используется для:

* истории проверок на стороне студента (трекинг прогресса),
* отображения diff между двумя версиями работы,
* отчётов руководителю о состоянии работ в группе.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone

from .schema import Submission, ViolationRecord


def record_submission(
    conn: sqlite3.Connection,
    *,
    filename: str,
    profile_id: str,
    violations: Iterable[object],
    created_at: str | None = None,
) -> int:
    """Записать submission и его violations в БД. Вернуть id submission.

    ``violations`` принимает любой iterable объектов с атрибутами
    ``check_code``, ``severity``, ``message``, ``location``,
    ``suggestion`` — совместимо с :class:`gostforge.validator.engine.Violation`.

    ``created_at`` — ISO 8601 UTC; если не задан, берётся текущее время.
    """
    ts = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    violation_list = list(violations)

    err = sum(1 for v in violation_list if getattr(v, "severity", "") == "error")
    warn = sum(1 for v in violation_list if getattr(v, "severity", "") == "warning")
    info = sum(1 for v in violation_list if getattr(v, "severity", "") == "info")

    cursor = conn.execute(
        """
        INSERT INTO submissions
            (filename, profile_id, created_at, error_count, warning_count, info_count)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (filename, profile_id, ts, err, warn, info),
    )
    submission_id = int(cursor.lastrowid or 0)

    if violation_list:
        conn.executemany(
            """
            INSERT INTO violations
                (submission_id, code, severity, message, location, suggestion)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    submission_id,
                    getattr(v, "check_code", ""),
                    getattr(v, "severity", ""),
                    getattr(v, "message", ""),
                    getattr(v, "location", "") or "",
                    getattr(v, "suggestion", "") or "",
                )
                for v in violation_list
            ],
        )
    conn.commit()
    return submission_id


def list_submissions(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    filename: str | None = None,
) -> list[Submission]:
    """Вернуть последние submission-ы в порядке от свежих к старым.

    Без подгрузки violations (только метаданные + счётчики) — для
    быстрой выборки «история». Чтобы получить детали — see
    :func:`get_submission`.
    """
    sql = "SELECT * FROM submissions"
    params: tuple[object, ...] = ()
    if filename is not None:
        sql += " WHERE filename = ?"
        params = (filename,)
    sql += " ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
    params = (*params, int(limit))

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_submission(row, violations=[]) for row in rows]


def get_submission(conn: sqlite3.Connection, submission_id: int) -> Submission | None:
    """Загрузить submission по id вместе со всеми violations.

    Возвращает ``None``, если такой submission не найден.
    """
    row = conn.execute(
        "SELECT * FROM submissions WHERE id = ?", (int(submission_id),)
    ).fetchone()
    if row is None:
        return None
    violations = [
        ViolationRecord(
            id=int(v["id"]),
            submission_id=int(v["submission_id"]),
            code=str(v["code"]),
            severity=str(v["severity"]),
            message=str(v["message"]),
            location=str(v["location"]),
            suggestion=str(v["suggestion"]),
        )
        for v in conn.execute(
            "SELECT * FROM violations WHERE submission_id = ? ORDER BY id",
            (int(submission_id),),
        ).fetchall()
    ]
    return _row_to_submission(row, violations=violations)


def delete_submission(conn: sqlite3.Connection, submission_id: int) -> bool:
    """Удалить submission и все его violations (через ON DELETE CASCADE).

    Возвращает True, если запись существовала и удалена, иначе False.
    """
    cursor = conn.execute(
        "DELETE FROM submissions WHERE id = ?", (int(submission_id),)
    )
    conn.commit()
    return (cursor.rowcount or 0) > 0


def _row_to_submission(row: sqlite3.Row, *, violations: list[ViolationRecord]) -> Submission:
    return Submission(
        id=int(row["id"]),
        filename=str(row["filename"]),
        profile_id=str(row["profile_id"]),
        created_at=str(row["created_at"]),
        error_count=int(row["error_count"]),
        warning_count=int(row["warning_count"]),
        info_count=int(row["info_count"]),
        violations=violations,
    )
