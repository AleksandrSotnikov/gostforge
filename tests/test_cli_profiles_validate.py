"""Тесты команды `gostforge profiles validate`."""

from pathlib import Path

from click.testing import CliRunner

from gostforge.cli import main


def test_validate_correct_profile() -> None:
    """Базовый профиль валиден и команда возвращает 0."""
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "validate", "profiles/gost-7.32-2017.yaml"])
    assert result.exit_code == 0
    assert "Файл валиден" in result.output
    assert "Профиль: gost-7.32-2017" in result.output


def test_validate_inherited_profile() -> None:
    """Профиль с extends также валиден."""
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "validate", "profiles/example-department.yaml"])
    assert result.exit_code == 0
    assert "Наследует от" in result.output


def test_validate_invalid_yaml(tmp_path: Path) -> None:
    """Битый YAML — exit 2 с ошибкой."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: test\nname: [oops, not a string", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "validate", str(bad)])
    assert result.exit_code == 2


def test_validate_missing_required_field(tmp_path: Path) -> None:
    """Профиль без обязательного `id` отклоняется pydantic-схемой."""
    bad = tmp_path / "no_id.yaml"
    bad.write_text("name: Test\nversion: '1.0'", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["profiles", "validate", str(bad)])
    assert result.exit_code == 2
