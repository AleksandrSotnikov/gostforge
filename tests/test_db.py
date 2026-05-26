# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты локальной SQLite-БД gostforge (Фаза 3).

Изолируем диск через monkeypatch GOSTFORGE_DB_PATH в tmp_path —
реальный ~/.gostforge/gostforge.db в тестах не трогаем.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from gostforge.db import (
    Submission,
    ViolationRecord,
    default_db_path,
    get_connection,
    get_submission,
    list_submissions,
    record_submission,
)
from gostforge.db.migrations import apply_migrations, current_schema_version
from gostforge.db.submissions import delete_submission


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированный путь БД в tmp_path через env."""
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


class _FakeViolation:
    """Мок Violation с полями, которые ожидает record_submission."""

    def __init__(
        self,
        code: str,
        severity: str,
        message: str,
        location: str = "",
        suggestion: str = "",
    ) -> None:
        self.check_code = code
        self.severity = severity
        self.message = message
        self.location = location
        self.suggestion = suggestion


# --- default_db_path -------------------------------------------------------


def test_default_db_path_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOSTFORGE_DB_PATH", "/tmp/custom-gostforge.db")
    assert default_db_path() == Path("/tmp/custom-gostforge.db")


def test_default_db_path_uses_home_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOSTFORGE_DB_PATH", raising=False)
    p = default_db_path()
    assert p.name == "gostforge.db"
    assert p.parent.name == ".gostforge"


# --- get_connection / auto-init --------------------------------------------


def test_get_connection_creates_directory(db_path: Path) -> None:
    """Каталог под БД создаётся, даже если parent не существует."""
    nested = db_path.parent / "nested" / "deep" / "gostforge.db"
    conn = get_connection(nested)
    assert nested.parent.is_dir()
    conn.close()


def test_get_connection_initializes_schema(db_path: Path) -> None:
    conn = get_connection()
    # Версия растёт с каждой добавленной миграцией; на момент теста
    # ожидаем хотя бы v1 (submissions+violations). Конкретное значение
    # не зашиваем, чтобы новые миграции не ломали этот тест.
    assert current_schema_version(conn) >= 1
    # Таблицы созданы.
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"submissions", "violations", "schema_version"} <= tables
    conn.close()


def test_get_connection_enables_foreign_keys(db_path: Path) -> None:
    """PRAGMA foreign_keys должен быть включён — иначе CASCADE не работает."""
    conn = get_connection()
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    conn.close()


def test_get_connection_idempotent(db_path: Path) -> None:
    """Повторное открытие на той же БД не делает дублирующих миграций."""
    conn1 = get_connection()
    initial_version = current_schema_version(conn1)
    initial_count = conn1.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    conn1.close()

    conn2 = get_connection()
    assert current_schema_version(conn2) == initial_version
    final_count = conn2.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert final_count == initial_count
    conn2.close()


def test_apply_migrations_idempotent_within_one_connection(db_path: Path) -> None:
    """Вызов apply_migrations второй раз на том же conn не падает и noop."""
    conn = get_connection()
    before = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    applied = apply_migrations(conn)
    after = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert applied == 0
    assert after == before
    conn.close()


# --- record_submission -----------------------------------------------------


def test_record_submission_returns_id(db_path: Path) -> None:
    conn = get_connection()
    sid = record_submission(
        conn,
        filename="thesis.docx",
        profile_id="gost-7.32-2017",
        violations=[],
    )
    assert isinstance(sid, int)
    assert sid > 0
    conn.close()


def test_record_submission_aggregates_severity_counts(db_path: Path) -> None:
    conn = get_connection()
    violations = [
        _FakeViolation("F.01", "error", "m1"),
        _FakeViolation("F.02", "error", "m2"),
        _FakeViolation("T.01", "warning", "m3"),
        _FakeViolation("X.01", "info", "m4"),
        _FakeViolation("X.02", "info", "m5"),
        _FakeViolation("X.03", "info", "m6"),
    ]
    sid = record_submission(
        conn,
        filename="w.docx",
        profile_id="gost-7.32-2017",
        violations=violations,
    )
    sub = get_submission(conn, sid)
    assert sub is not None
    assert sub.error_count == 2
    assert sub.warning_count == 1
    assert sub.info_count == 3
    assert len(sub.violations) == 6
    conn.close()


def test_record_submission_preserves_violation_order(db_path: Path) -> None:
    conn = get_connection()
    codes_in = ["A.01", "B.01", "C.01", "D.01"]
    violations = [_FakeViolation(c, "error", f"msg-{c}") for c in codes_in]
    sid = record_submission(
        conn, filename="x.docx", profile_id="gost-7.32-2017", violations=violations
    )
    sub = get_submission(conn, sid)
    assert sub is not None
    assert [v.code for v in sub.violations] == codes_in
    conn.close()


def test_record_submission_accepts_custom_timestamp(db_path: Path) -> None:
    conn = get_connection()
    sid = record_submission(
        conn,
        filename="x.docx",
        profile_id="gost-7.32-2017",
        violations=[],
        created_at="2026-01-15T12:00:00+00:00",
    )
    sub = get_submission(conn, sid)
    assert sub is not None
    assert sub.created_at == "2026-01-15T12:00:00+00:00"
    conn.close()


# --- list_submissions ------------------------------------------------------


def test_list_submissions_returns_newest_first(db_path: Path) -> None:
    conn = get_connection()
    record_submission(
        conn,
        filename="old.docx",
        profile_id="gost-7.32-2017",
        violations=[],
        created_at="2026-01-01T00:00:00+00:00",
    )
    record_submission(
        conn,
        filename="new.docx",
        profile_id="gost-7.32-2017",
        violations=[],
        created_at="2026-06-01T00:00:00+00:00",
    )
    items = list_submissions(conn)
    assert items[0].filename == "new.docx"
    assert items[1].filename == "old.docx"
    conn.close()


def test_list_submissions_respects_limit(db_path: Path) -> None:
    conn = get_connection()
    for i in range(10):
        record_submission(
            conn,
            filename=f"f{i}.docx",
            profile_id="gost-7.32-2017",
            violations=[],
        )
    assert len(list_submissions(conn, limit=3)) == 3
    assert len(list_submissions(conn, limit=100)) == 10
    conn.close()


def test_list_submissions_filter_by_filename(db_path: Path) -> None:
    conn = get_connection()
    record_submission(conn, filename="a.docx", profile_id="x", violations=[])
    record_submission(conn, filename="a.docx", profile_id="x", violations=[])
    record_submission(conn, filename="b.docx", profile_id="x", violations=[])
    a_only = list_submissions(conn, filename="a.docx")
    assert len(a_only) == 2
    assert all(s.filename == "a.docx" for s in a_only)
    conn.close()


def test_list_submissions_does_not_load_violations(db_path: Path) -> None:
    """list_submissions возвращает только метаданные — violations пустой."""
    conn = get_connection()
    sid = record_submission(
        conn,
        filename="x.docx",
        profile_id="x",
        violations=[_FakeViolation("F.01", "error", "m")],
    )
    items = list_submissions(conn)
    target = next(s for s in items if s.id == sid)
    assert target.violations == []
    # Но счётчик отражает реальность.
    assert target.error_count == 1
    conn.close()


# --- get_submission / delete -----------------------------------------------


def test_get_submission_returns_none_for_unknown_id(db_path: Path) -> None:
    conn = get_connection()
    assert get_submission(conn, 999) is None
    conn.close()


def test_delete_submission_cascades_to_violations(db_path: Path) -> None:
    """ON DELETE CASCADE — удаление submission уносит и violations."""
    conn = get_connection()
    sid = record_submission(
        conn,
        filename="x.docx",
        profile_id="x",
        violations=[_FakeViolation("F.01", "error", "m")],
    )
    before = conn.execute("SELECT COUNT(*) FROM violations").fetchone()[0]
    assert before >= 1

    assert delete_submission(conn, sid) is True
    after = conn.execute("SELECT COUNT(*) FROM violations").fetchone()[0]
    assert after == 0
    assert get_submission(conn, sid) is None
    conn.close()


def test_delete_unknown_submission_returns_false(db_path: Path) -> None:
    conn = get_connection()
    assert delete_submission(conn, 999) is False
    conn.close()


# --- Schema integrity ------------------------------------------------------


def test_submission_dataclass_round_trip(db_path: Path) -> None:
    """Submission и ViolationRecord корректно гидратируются обратно."""
    conn = get_connection()
    sid = record_submission(
        conn,
        filename="x.docx",
        profile_id="gost-7.32-2017",
        violations=[
            _FakeViolation("F.01", "error", "msg", "loc-1", "fix-1"),
        ],
    )
    sub = get_submission(conn, sid)
    assert isinstance(sub, Submission)
    assert sub.filename == "x.docx"
    v = sub.violations[0]
    assert isinstance(v, ViolationRecord)
    assert v.code == "F.01"
    assert v.location == "loc-1"
    assert v.suggestion == "fix-1"
    conn.close()


def test_can_be_used_as_context_manager(db_path: Path) -> None:
    """sqlite3.Connection поддерживает with — commit на выходе."""
    with get_connection() as conn:
        record_submission(conn, filename="x.docx", profile_id="x", violations=[])
    # Открываем заново — запись на месте.
    with get_connection() as conn:
        items = list_submissions(conn)
        assert any(s.filename == "x.docx" for s in items)


def test_pragma_journal_mode_is_wal(db_path: Path) -> None:
    """WAL — лучшая параллельность read/write; должен быть включён."""
    conn = get_connection()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    conn.close()
