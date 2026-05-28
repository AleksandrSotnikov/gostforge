"""Тесты CLI-команды `gostforge diff` — сравнение двух .docx по нарушениям."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from gostforge.cli import main
from tests.conftest import GOST_MARGINS, make_docx


def _clean_docx(path: Path) -> Path:
    """Документ без явных нарушений T-категории."""
    return make_docx(
        path,
        margins_mm=dict(GOST_MARGINS),
        paragraphs=["Обычный абзац без нарушений."],
        headings=[(1, "Введение"), (1, "Заключение"), (1, "Список использованных источников")],
        page_number=True,
    )


def _double_space_docx(path: Path) -> Path:
    """Документ с двойным пробелом — нарушение T.08."""
    return make_docx(
        path,
        margins_mm=dict(GOST_MARGINS),
        paragraphs=["Текст  с двойным пробелом."],
        headings=[(1, "Введение"), (1, "Заключение"), (1, "Список использованных источников")],
        page_number=True,
    )


def _double_space_and_quotes_docx(path: Path) -> Path:
    """Документ с двойным пробелом И парными кавычками — два разных нарушения."""
    return make_docx(
        path,
        margins_mm=dict(GOST_MARGINS),
        paragraphs=['"a  b" — двойные пробелы и кавычки.'],
        headings=[(1, "Введение"), (1, "Заключение"), (1, "Список использованных источников")],
        page_number=True,
    )


def test_diff_identical_files_reports_no_changes(tmp_path: Path) -> None:
    """Если оба файла дают одинаковый набор нарушений — diff сообщает «изменений нет»."""
    src_a = _double_space_docx(tmp_path / "a.docx")
    src_b = _double_space_docx(tmp_path / "b.docx")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["diff", str(src_a), str(src_b)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "Изменений в нарушениях нет" in result.output


def test_diff_fix_reduces_violations(tmp_path: Path) -> None:
    """Если в B нарушений меньше (например, применён fix) — diff показывает «исчезло»."""
    src_a = _double_space_docx(tmp_path / "a.docx")
    src_b = _clean_docx(tmp_path / "b.docx")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["diff", str(src_a), str(src_b)],
        catch_exceptions=False,
    )

    # exit 0: errors не выросли, регрессии нет.
    assert result.exit_code == 0, result.output
    assert "Исчезло нарушений" in result.output
    # T.08 в исчезнувших должен присутствовать.
    assert "T.08" in result.output


def test_diff_introduced_violations_listed(tmp_path: Path) -> None:
    """B содержит новые T.08/T.10 нарушения которых не было в A → они попадают в «появилось»."""
    src_a = _clean_docx(tmp_path / "a.docx")
    src_b = _double_space_and_quotes_docx(tmp_path / "b.docx")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["diff", str(src_a), str(src_b)],
        catch_exceptions=False,
    )

    assert "Появилось нарушений" in result.output
    # T.08 (двойной пробел) — должен попасть в новые.
    assert "T.08" in result.output


def test_diff_regression_with_real_error_returns_exit_1(tmp_path: Path) -> None:
    """B с явным error-нарушением (неправильные поля F.01) против чистого A — exit 1.

    Берём ОДИНАКОВЫЙ контент A и B (так что прочие нарушения тождественны),
    но в B портим поля страницы — это добавляет ровно один error F.01 поверх
    остальных. Total errors_b > errors_a → exit 1.
    """
    src_a = make_docx(
        tmp_path / "a.docx",
        margins_mm=dict(GOST_MARGINS),
        paragraphs=["Идентичный текст."],
        headings=[(1, "Введение"), (1, "Заключение"), (1, "Список использованных источников")],
        page_number=True,
    )
    bad_margins = dict(GOST_MARGINS)
    bad_margins["top"] = 50
    src_b = make_docx(
        tmp_path / "b.docx",
        margins_mm=bad_margins,
        paragraphs=["Идентичный текст."],
        headings=[(1, "Введение"), (1, "Заключение"), (1, "Список использованных источников")],
        page_number=True,
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["diff", str(src_a), str(src_b)],
        catch_exceptions=False,
    )

    assert "Появилось нарушений" in result.output
    assert "Регрессия" in result.output
    assert result.exit_code == 1


def test_diff_nonexistent_file_returns_exit_2(tmp_path: Path) -> None:
    """Несуществующий путь к файлу — click возвращает exit 2."""
    src_a = _clean_docx(tmp_path / "a.docx")
    missing = tmp_path / "does_not_exist.docx"

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["diff", str(src_a), str(missing)],
        catch_exceptions=False,
    )

    assert result.exit_code == 2
