"""Тесты CLI 'gostforge comment add/list/resolve/delete' + интеграция с history."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from gostforge.cli import main

from .conftest import make_docx


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


@pytest.fixture
def submission_id(db_path: Path, tmp_path: Path) -> int:
    """Подготовить submission через gostforge check."""
    docx = tmp_path / "sample.docx"
    make_docx(docx, paragraphs=["Текст"])
    CliRunner().invoke(main, ["check", str(docx), "--quiet"])
    from gostforge.db import get_connection, list_submissions

    with get_connection() as conn:
        items = list_submissions(conn)
    sid = items[0].id
    assert sid is not None
    return sid


# --- comment add -----------------------------------------------------------


def test_add_comment_happy_path(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "comment",
            "add",
            str(submission_id),
            "Переделай введение",
            "--role",
            "supervisor",
            "--author",
            "prof@univ.ru",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Комментарий добавлен" in result.output
    assert "supervisor" in result.output


def test_add_uses_default_author_from_env(
    db_path: Path,
    submission_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOSTFORGE_DEFAULT_AUTHOR", "student@kafedra.ru")
    runner = CliRunner()
    result = runner.invoke(main, ["comment", "add", str(submission_id), "Просто комментарий"])
    assert result.exit_code == 0
    assert "student@kafedra.ru" in result.output


def test_add_with_unknown_submission_returns_2(db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["comment", "add", "999", "test"])
    assert result.exit_code == 2
    assert "не существует" in result.output


def test_add_with_empty_body_returns_2(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["comment", "add", str(submission_id), "   "])
    assert result.exit_code == 2
    assert "пустым" in result.output


def test_add_with_invalid_role_handled_by_click(db_path: Path, submission_id: int) -> None:
    """click.Choice сам отвергает невалидное значение --role."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["comment", "add", str(submission_id), "x", "--role", "admin"],
    )
    assert result.exit_code != 0
    # click печатает 'Invalid value' с перечнем допустимых.


# --- comment list ----------------------------------------------------------


def test_list_empty(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["comment", "list", str(submission_id)])
    assert result.exit_code == 0
    assert "нет" in result.output.lower()


def test_list_shows_chronological_with_markers(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    runner.invoke(main, ["comment", "add", str(submission_id), "open one", "--role", "student"])
    runner.invoke(
        main,
        ["comment", "add", str(submission_id), "open two", "--role", "supervisor"],
    )
    result = runner.invoke(main, ["comment", "list", str(submission_id)])
    assert result.exit_code == 0
    assert "open one" in result.output
    assert "open two" in result.output
    assert "[student]" in result.output
    assert "[supervisor]" in result.output
    # Открытые — должны быть ● (yellow circle).
    assert "●" in result.output


def test_list_unresolved_hides_closed(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    runner.invoke(main, ["comment", "add", str(submission_id), "open"])
    runner.invoke(main, ["comment", "add", str(submission_id), "closed"])
    # Закрываем второй комментарий.
    runner.invoke(main, ["comment", "resolve", "2"])
    result = runner.invoke(main, ["comment", "list", str(submission_id), "--unresolved"])
    assert "open" in result.output
    assert "closed" not in result.output


# --- comment resolve / reopen ----------------------------------------------


def test_resolve_marks_closed(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    runner.invoke(main, ["comment", "add", str(submission_id), "x"])
    result = runner.invoke(main, ["comment", "resolve", "1"])
    assert result.exit_code == 0
    assert "закрыт" in result.output


def test_reopen_flag_unmarks(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    runner.invoke(main, ["comment", "add", str(submission_id), "x"])
    runner.invoke(main, ["comment", "resolve", "1"])
    result = runner.invoke(main, ["comment", "resolve", "1", "--reopen"])
    assert result.exit_code == 0
    assert "переоткрыт" in result.output


def test_resolve_unknown_comment_returns_1(db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["comment", "resolve", "999"])
    assert result.exit_code == 1
    assert "не найден" in result.output


# --- comment delete --------------------------------------------------------


def test_delete_removes_comment(db_path: Path, submission_id: int) -> None:
    runner = CliRunner()
    runner.invoke(main, ["comment", "add", str(submission_id), "x"])
    result = runner.invoke(main, ["comment", "delete", "1"])
    assert result.exit_code == 0
    assert "удалён" in result.output
    # Список пустой.
    list_result = runner.invoke(main, ["comment", "list", str(submission_id)])
    assert "нет" in list_result.output.lower()


def test_delete_unknown_returns_1(db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["comment", "delete", "999"])
    assert result.exit_code == 1


# --- интеграция: history --id показывает комментарии ----------------------


def test_history_id_shows_comments(db_path: Path, submission_id: int) -> None:
    """gostforge history --id N показывает submission + комментарии."""
    runner = CliRunner()
    runner.invoke(
        main,
        ["comment", "add", str(submission_id), "Замечание", "--role", "supervisor"],
    )
    result = runner.invoke(main, ["history", "--id", str(submission_id)])
    assert result.exit_code == 0
    assert "Комментарии:" in result.output
    assert "Замечание" in result.output
    assert "[supervisor]" in result.output


def test_history_id_without_comments_shows_no_section(db_path: Path, submission_id: int) -> None:
    """Без комментариев секция «Комментарии:» не показывается."""
    runner = CliRunner()
    result = runner.invoke(main, ["history", "--id", str(submission_id)])
    assert result.exit_code == 0
    assert "Комментарии:" not in result.output
