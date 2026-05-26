# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты UI-режима «История и обсуждение» (Streamlit).

Тестируем чистые функции — _try_list_submissions, _try_get_submission,
_try_list_comments, _try_unresolved_count, _add_comment_action,
_resolve_comment_action, _delete_comment_action, _escape_html. UI-
функции (_render_*) проверяем только через факт импорта и smoke-вызов
render_history_viewer без поднятия реальной сессии Streamlit (через
test client отдельно — в test_web_smoke.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from gostforge.web.history_viewer import (
    _add_comment_action,
    _delete_comment_action,
    _escape_html,
    _resolve_comment_action,
    _try_get_submission,
    _try_list_comments,
    _try_list_submissions,
    _try_unresolved_count,
    render_history_viewer,
)


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


@pytest.fixture
def submission_id(db_path: Path) -> int:
    """Подготовить submission в изолированной БД."""
    from gostforge.db import get_connection, record_submission

    with get_connection() as conn:
        return record_submission(
            conn,
            filename="thesis.docx",
            profile_id="gost-7.32-2017",
            violations=[],
        )


# --- _try_list_submissions / _try_get_submission --------------------------


def test_try_list_returns_records(db_path: Path, submission_id: int) -> None:
    items = _try_list_submissions(filename=None)
    assert len(items) == 1
    assert items[0].filename == "thesis.docx"


def test_try_list_filters_by_filename(db_path: Path) -> None:
    from gostforge.db import get_connection, record_submission

    with get_connection() as conn:
        record_submission(
            conn, filename="a.docx", profile_id="gost-7.32-2017", violations=[]
        )
        record_submission(
            conn, filename="b.docx", profile_id="gost-7.32-2017", violations=[]
        )
    items = _try_list_submissions(filename="a.docx")
    assert len(items) == 1
    assert items[0].filename == "a.docx"


def test_try_list_empty_when_no_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если БД недоступна — пустой список вместо exception."""
    monkeypatch.setenv("GOSTFORGE_DB_PATH", "/nonexistent/path/x.db")
    # Каталог не создаётся (на /nonexistent нет прав) → graceful [].
    items = _try_list_submissions(filename=None)
    assert items == []


def test_try_get_submission_returns_full_record(
    db_path: Path, submission_id: int
) -> None:
    sub = _try_get_submission(submission_id)
    assert sub is not None
    assert sub.id == submission_id


def test_try_get_submission_returns_none_for_unknown(db_path: Path) -> None:
    assert _try_get_submission(999) is None


# --- _try_list_comments / _try_unresolved_count ---------------------------


def test_try_list_comments_empty(db_path: Path, submission_id: int) -> None:
    assert _try_list_comments(submission_id) == []


def test_try_list_comments_returns_in_order(
    db_path: Path, submission_id: int
) -> None:
    ok1, _ = _add_comment_action(
        submission_id=submission_id, body="first", author="a", role="student"
    )
    ok2, _ = _add_comment_action(
        submission_id=submission_id,
        body="second",
        author="b",
        role="supervisor",
    )
    assert ok1 and ok2
    items = _try_list_comments(submission_id)
    assert [c.body for c in items] == ["first", "second"]


def test_try_unresolved_count(db_path: Path, submission_id: int) -> None:
    _add_comment_action(
        submission_id=submission_id, body="open", author="", role="anonymous"
    )
    assert _try_unresolved_count(submission_id) == 1


# --- _add_comment_action ---------------------------------------------------


def test_add_comment_empty_body_returns_error(
    db_path: Path, submission_id: int
) -> None:
    ok, msg = _add_comment_action(
        submission_id=submission_id, body="   ", author="", role="anonymous"
    )
    assert ok is False
    assert "пустым" in msg.lower()


def test_add_comment_unknown_submission_returns_error(db_path: Path) -> None:
    ok, msg = _add_comment_action(
        submission_id=999, body="x", author="", role="anonymous"
    )
    assert ok is False
    assert "не существует" in msg


def test_add_comment_invalid_role_returns_error(
    db_path: Path, submission_id: int
) -> None:
    ok, msg = _add_comment_action(
        submission_id=submission_id, body="x", author="", role="admin"
    )
    assert ok is False
    assert "role" in msg.lower()


def test_add_comment_happy_path(db_path: Path, submission_id: int) -> None:
    ok, msg = _add_comment_action(
        submission_id=submission_id,
        body="Переделай",
        author="prof",
        role="supervisor",
    )
    assert ok is True
    assert "добавлен" in msg.lower()


# --- _resolve_comment_action / _delete_comment_action ---------------------


def test_resolve_existing_comment(db_path: Path, submission_id: int) -> None:
    _add_comment_action(
        submission_id=submission_id, body="x", author="", role="anonymous"
    )
    items = _try_list_comments(submission_id)
    assert _resolve_comment_action(items[0].id, resolved=True) is True
    # После закрытия unresolved=0.
    assert _try_unresolved_count(submission_id) == 0


def test_resolve_unknown_returns_false(db_path: Path) -> None:
    assert _resolve_comment_action(999, resolved=True) is False


def test_reopen_resolved_comment(db_path: Path, submission_id: int) -> None:
    _add_comment_action(
        submission_id=submission_id, body="x", author="", role="anonymous"
    )
    items = _try_list_comments(submission_id)
    _resolve_comment_action(items[0].id, resolved=True)
    assert _resolve_comment_action(items[0].id, resolved=False) is True
    assert _try_unresolved_count(submission_id) == 1


def test_delete_comment(db_path: Path, submission_id: int) -> None:
    _add_comment_action(
        submission_id=submission_id, body="x", author="", role="anonymous"
    )
    items = _try_list_comments(submission_id)
    assert _delete_comment_action(items[0].id) is True
    assert _try_list_comments(submission_id) == []


def test_delete_unknown_returns_false(db_path: Path) -> None:
    assert _delete_comment_action(999) is False


# --- _escape_html ----------------------------------------------------------


def test_escape_html_basic() -> None:
    assert _escape_html("<script>") == "&lt;script&gt;"


def test_escape_html_ampersand() -> None:
    assert "&amp;" in _escape_html("AT&T")


def test_escape_html_preserves_newlines_as_br() -> None:
    assert "<br>" in _escape_html("first\nsecond")


def test_escape_html_no_tags_in_plain_text() -> None:
    out = _escape_html("обычный текст")
    assert out == "обычный текст"


# --- smoke ----------------------------------------------------------------


def test_render_history_viewer_importable() -> None:
    """Функция импортируется и вызываема."""
    assert callable(render_history_viewer)
