# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты таблицы comments (миграция v3 — совместная работа)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gostforge.db import (
    Comment,
    add_comment,
    count_unresolved_comments,
    delete_comment,
    get_comment,
    get_connection,
    list_comments,
    record_submission,
    resolve_comment,
)
from gostforge.db.migrations import current_schema_version


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


@pytest.fixture
def submission_id(db_path: Path) -> int:
    """Подготовить submission, к которому будут привязаны комментарии."""
    with get_connection() as conn:
        return record_submission(
            conn, filename="thesis.docx", profile_id="gost-7.32-2017", violations=[]
        )


# --- Миграция --------------------------------------------------------------


def test_migration_v3_creates_comments_table(db_path: Path) -> None:
    with get_connection() as conn:
        assert current_schema_version(conn) >= 3
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "comments" in tables


# --- add_comment -----------------------------------------------------------


def test_add_comment_returns_record(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        c = add_comment(
            conn,
            submission_id=submission_id,
            body="Проверь введение",
            author="prof@univ.ru",
            role="supervisor",
        )
    assert isinstance(c, Comment)
    assert c.body == "Проверь введение"
    assert c.role == "supervisor"
    assert c.resolved is False
    assert c.created_at  # ISO-метка


def test_add_comment_trims_body(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        c = add_comment(
            conn, submission_id=submission_id, body="   ok   ", role="student"
        )
    assert c.body == "ok"


def test_add_comment_rejects_empty_body(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        with pytest.raises(ValueError, match="пустым"):
            add_comment(conn, submission_id=submission_id, body="")
        with pytest.raises(ValueError, match="пустым"):
            add_comment(conn, submission_id=submission_id, body="    ")


def test_add_comment_rejects_invalid_role(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        with pytest.raises(ValueError, match="role"):
            add_comment(
                conn, submission_id=submission_id, body="x", role="admin"
            )


def test_add_comment_rejects_unknown_submission(db_path: Path) -> None:
    """submission_id должен существовать — иначе понятная ValueError."""
    with get_connection() as conn:
        with pytest.raises(ValueError, match="не существует"):
            add_comment(conn, submission_id=999, body="x")


def test_add_comment_default_role_anonymous(
    db_path: Path, submission_id: int
) -> None:
    with get_connection() as conn:
        c = add_comment(conn, submission_id=submission_id, body="x")
    assert c.role == "anonymous"
    assert c.author == ""


# --- list_comments ---------------------------------------------------------


def test_list_comments_chronological(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        add_comment(
            conn,
            submission_id=submission_id,
            body="первый",
            created_at="2026-01-01T10:00:00+00:00",
        )
        add_comment(
            conn,
            submission_id=submission_id,
            body="второй",
            created_at="2026-01-02T10:00:00+00:00",
        )
        items = list_comments(conn, submission_id=submission_id)
    assert [c.body for c in items] == ["первый", "второй"]


def test_list_comments_filter_resolved(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        c1 = add_comment(conn, submission_id=submission_id, body="open")
        c2 = add_comment(conn, submission_id=submission_id, body="closed")
        assert c1.id is not None
        assert c2.id is not None
        resolve_comment(conn, c2.id)
        all_items = list_comments(conn, submission_id=submission_id)
        only_open = list_comments(
            conn, submission_id=submission_id, include_resolved=False
        )
    assert len(all_items) == 2
    assert len(only_open) == 1
    assert only_open[0].body == "open"


def test_list_comments_empty_for_unknown_submission(db_path: Path) -> None:
    with get_connection() as conn:
        items = list_comments(conn, submission_id=999)
    assert items == []


# --- get / resolve / delete -------------------------------------------------


def test_get_comment_by_id(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        c = add_comment(conn, submission_id=submission_id, body="hi")
        assert c.id is not None
        got = get_comment(conn, c.id)
    assert got is not None
    assert got.body == "hi"


def test_get_unknown_comment_returns_none(db_path: Path) -> None:
    with get_connection() as conn:
        assert get_comment(conn, 999) is None


def test_resolve_comment_toggles_flag(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        c = add_comment(conn, submission_id=submission_id, body="x")
        assert c.id is not None
        assert resolve_comment(conn, c.id, resolved=True) is True
        got = get_comment(conn, c.id)
        assert got is not None
        assert got.resolved is True
        # Снять отметку — тоже работает.
        assert resolve_comment(conn, c.id, resolved=False) is True
        got = get_comment(conn, c.id)
        assert got is not None
        assert got.resolved is False


def test_resolve_unknown_comment_returns_false(db_path: Path) -> None:
    with get_connection() as conn:
        assert resolve_comment(conn, 999) is False


def test_delete_comment(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        c = add_comment(conn, submission_id=submission_id, body="x")
        assert c.id is not None
        assert delete_comment(conn, c.id) is True
        assert get_comment(conn, c.id) is None
        assert delete_comment(conn, c.id) is False  # повторный — False


def test_delete_submission_cascades_to_comments(
    db_path: Path, submission_id: int
) -> None:
    """ON DELETE CASCADE: удаление submission уносит свои комментарии."""
    from gostforge.db.submissions import delete_submission

    with get_connection() as conn:
        add_comment(conn, submission_id=submission_id, body="will be deleted")
        assert delete_submission(conn, submission_id) is True
        items = list_comments(conn, submission_id=submission_id)
    assert items == []


# --- count_unresolved_comments --------------------------------------------


def test_count_unresolved(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        c1 = add_comment(conn, submission_id=submission_id, body="open1")
        c2 = add_comment(conn, submission_id=submission_id, body="open2")
        c3 = add_comment(conn, submission_id=submission_id, body="closed")
        assert c3.id is not None
        resolve_comment(conn, c3.id)
        n = count_unresolved_comments(conn, submission_id)
    assert n == 2
    _ = c1, c2  # silence unused


def test_count_unresolved_zero(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        assert count_unresolved_comments(conn, submission_id) == 0


# --- Роли ------------------------------------------------------------------


def test_all_three_roles_allowed(db_path: Path, submission_id: int) -> None:
    with get_connection() as conn:
        for role in ("student", "supervisor", "anonymous"):
            add_comment(conn, submission_id=submission_id, body=role, role=role)
        items = list_comments(conn, submission_id=submission_id)
    assert {c.role for c in items} == {"student", "supervisor", "anonymous"}
