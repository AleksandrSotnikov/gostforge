# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты CLI 'gostforge profiles install/uninstall/list' (Фаза 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from gostforge.cli import main


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "gostforge.db"
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(p))
    return p


@pytest.fixture
def yaml_file(tmp_path: Path) -> Path:
    p = tmp_path / "kafedra.yaml"
    p.write_text(
        'id: my-kafedra\nname: Моя кафедра\nversion: "1.0"\nextends: gost-7.32-2017\n',
        encoding="utf-8",
    )
    return p


# --- install ---------------------------------------------------------------


def test_install_happy_path(db_path: Path, yaml_file: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "install", str(yaml_file)])
    assert result.exit_code == 0, result.output
    assert "Профиль установлен" in result.output
    assert "my-kafedra" in result.output

    # Профиль теперь виден в list.
    list_result = runner.invoke(main, ["profiles", "list"])
    assert "my-kafedra" in list_result.output
    assert "[custom]" in list_result.output


def test_install_unknown_file_returns_error(db_path: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    nonexistent = tmp_path / "nope.yaml"
    result = runner.invoke(main, ["profiles", "install", str(nonexistent)])
    # click.Path(exists=True) сам поднимет код 2.
    assert result.exit_code != 0


def test_install_invalid_yaml_reports_error(db_path: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("description: только описание\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "install", str(bad)])
    assert result.exit_code == 2
    assert "Ошибка" in result.output


def test_install_duplicate_without_overwrite_fails(db_path: Path, yaml_file: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["profiles", "install", str(yaml_file)])
    result = runner.invoke(main, ["profiles", "install", str(yaml_file)])
    assert result.exit_code == 2
    assert "уже установлен" in result.output


def test_install_with_overwrite_succeeds(db_path: Path, yaml_file: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["profiles", "install", str(yaml_file)])
    result = runner.invoke(main, ["profiles", "install", str(yaml_file), "--overwrite"])
    assert result.exit_code == 0
    assert "Профиль установлен" in result.output


# --- uninstall -------------------------------------------------------------


def test_uninstall_existing_profile(db_path: Path, yaml_file: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["profiles", "install", str(yaml_file)])

    result = runner.invoke(main, ["profiles", "uninstall", "my-kafedra"])
    assert result.exit_code == 0
    assert "удалён" in result.output

    # И в list его больше нет.
    list_result = runner.invoke(main, ["profiles", "list"])
    assert "my-kafedra" not in list_result.output


def test_uninstall_unknown_profile_returns_error(db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "uninstall", "does-not-exist"])
    assert result.exit_code == 1
    assert "не установлен" in result.output


def test_uninstall_builtin_profile_returns_error(db_path: Path) -> None:
    """Builtin-профили (из каталога пакета) удалить нельзя — их нет в БД."""
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "uninstall", "gost-7.32-2017"])
    assert result.exit_code == 1
    # В БД его нет, поэтому uninstall говорит «не установлен».
    assert "не установлен" in result.output


# --- list ------------------------------------------------------------------


def test_list_marks_builtin_and_custom(db_path: Path, yaml_file: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["profiles", "install", str(yaml_file)])
    result = runner.invoke(main, ["profiles", "list"])
    assert result.exit_code == 0
    # Builtin есть и помечен.
    assert "gost-7.32-2017" in result.output
    assert "[builtin]" in result.output
    # Custom есть и помечен.
    assert "my-kafedra" in result.output
    assert "[custom]" in result.output


# --- end-to-end: check с custom-профилем -----------------------------------


def test_check_works_with_installed_custom_profile(
    db_path: Path, yaml_file: Path, tmp_path: Path
) -> None:
    """End-to-end: установили профиль, проверили работу с ним."""
    from .conftest import make_docx

    runner = CliRunner()
    install_result = runner.invoke(main, ["profiles", "install", str(yaml_file)])
    assert install_result.exit_code == 0

    docx = tmp_path / "sample.docx"
    make_docx(docx, paragraphs=["Текст"])
    check_result = runner.invoke(
        main,
        ["check", str(docx), "--profile", "my-kafedra", "--quiet", "--no-record"],
    )
    assert check_result.exit_code in (0, 1)
    # Самое главное — профиль найден, ошибки «не найден» нет.
    assert "не найден" not in check_result.output.lower()
    assert "not found" not in check_result.output.lower()
