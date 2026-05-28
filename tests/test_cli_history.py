"""Тесты CLI-команды `gostforge history` и автозаписи submission в check.

Изолируем БД через env GOSTFORGE_DB_PATH в tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from gostforge.cli import main

from .conftest import make_docx


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированная БД на тест."""
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


@pytest.fixture
def sample_docx(tmp_path: Path) -> Path:
    """Простой синтетический .docx для check."""
    p = tmp_path / "sample.docx"
    make_docx(p, paragraphs=["Текст."])
    return p


# --- автозапись из check ---------------------------------------------------


def test_check_records_submission_by_default(db_path: Path, sample_docx: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["check", str(sample_docx), "--quiet"])
    # exit code зависит от того, нашлись ли error-violations; нас интересует
    # только сам факт прогона без падения.
    assert result.exit_code in (0, 1), result.output

    # Проверим, что submission записан.
    from gostforge.db import get_connection, list_submissions

    with get_connection() as conn:
        items = list_submissions(conn)
    assert len(items) == 1
    assert items[0].filename == sample_docx.name


def test_check_no_record_skips_db(db_path: Path, sample_docx: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["check", str(sample_docx), "--quiet", "--no-record"])
    assert result.exit_code in (0, 1)

    from gostforge.db import get_connection, list_submissions

    with get_connection() as conn:
        items = list_submissions(conn)
    assert len(items) == 0


def test_check_records_each_file_when_directory(db_path: Path, tmp_path: Path) -> None:
    """check на папке должен записать submission для каждого .docx."""
    folder = tmp_path / "docs"
    folder.mkdir()
    for i in range(3):
        make_docx(folder / f"f{i}.docx", paragraphs=[f"file {i}"])

    runner = CliRunner()
    result = runner.invoke(main, ["check", str(folder), "--quiet"])
    assert result.exit_code in (0, 1)

    from gostforge.db import get_connection, list_submissions

    with get_connection() as conn:
        items = list_submissions(conn, limit=100)
    assert len(items) == 3
    assert {s.filename for s in items} == {"f0.docx", "f1.docx", "f2.docx"}


# --- history команда -------------------------------------------------------


def test_history_empty_db_shows_hint(db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["history"])
    assert result.exit_code == 0
    assert "История пуста" in result.output
    assert "gostforge check" in result.output


def test_history_shows_recent_submissions(db_path: Path, sample_docx: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["check", str(sample_docx), "--quiet"])
    result = runner.invoke(main, ["history"])
    assert result.exit_code == 0
    assert sample_docx.name in result.output
    # Должна быть строка вида "#   1  ..."
    assert "#   1" in result.output


def test_history_limit_caps_output(db_path: Path, tmp_path: Path) -> None:
    """--limit 2 показывает только 2 последних."""
    for i in range(5):
        p = tmp_path / f"f{i}.docx"
        make_docx(p, paragraphs=[f"x{i}"])
        CliRunner().invoke(main, ["check", str(p), "--quiet"])

    result = CliRunner().invoke(main, ["history", "--limit", "2"])
    assert result.exit_code == 0
    # Должно быть 2 строки с submission-id (символ '#').
    submission_lines = [
        line for line in result.output.splitlines() if line.lstrip().startswith("#")
    ]
    assert len(submission_lines) == 2


def test_history_filter_by_filename(db_path: Path, tmp_path: Path) -> None:
    """--filename выбирает только записи с этим именем."""
    p1 = tmp_path / "alpha.docx"
    p2 = tmp_path / "beta.docx"
    make_docx(p1, paragraphs=["x"])
    make_docx(p2, paragraphs=["x"])
    runner = CliRunner()
    runner.invoke(main, ["check", str(p1), "--quiet"])
    runner.invoke(main, ["check", str(p2), "--quiet"])

    result = runner.invoke(main, ["history", "--filename", "alpha.docx"])
    assert result.exit_code == 0
    assert "alpha.docx" in result.output
    assert "beta.docx" not in result.output


def test_history_id_shows_details(db_path: Path, sample_docx: Path) -> None:
    """--id <N> показывает детали со списком нарушений."""
    runner = CliRunner()
    runner.invoke(main, ["check", str(sample_docx), "--quiet"])
    result = runner.invoke(main, ["history", "--id", "1"])
    assert result.exit_code == 0
    assert "Submission #1" in result.output
    assert sample_docx.name in result.output


def test_history_id_unknown_returns_error(db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["history", "--id", "999"])
    assert result.exit_code == 1
    assert "не найден" in result.output
