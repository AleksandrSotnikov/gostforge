"""Тесты CLI-команд группы `gostforge plugins`."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from gostforge.cli import main


def test_plugins_dir_creates_directory(tmp_path: Path) -> None:
    """`gostforge plugins dir` создаёт директорию, если её нет."""
    target = tmp_path / ".gostforge" / "plugins"
    assert not target.exists()
    runner = CliRunner()
    with patch("gostforge.plugins.plugins_dir", return_value=target):
        result = runner.invoke(main, ["plugins", "dir"])
    assert result.exit_code == 0
    assert "Создана" in result.output
    assert target.exists()


def test_plugins_dir_existing(tmp_path: Path) -> None:
    """`gostforge plugins dir` выводит путь, если директория уже есть."""
    target = tmp_path / "plugins"
    target.mkdir()
    runner = CliRunner()
    with patch("gostforge.plugins.plugins_dir", return_value=target):
        result = runner.invoke(main, ["plugins", "dir"])
    assert result.exit_code == 0
    assert str(target) in result.output
    assert "Создана" not in result.output


def test_plugins_list_missing_directory(tmp_path: Path) -> None:
    """`gostforge plugins list` без директории — подсказка пользователю."""
    target = tmp_path / "nope"
    runner = CliRunner()
    with patch("gostforge.plugins.plugins_dir", return_value=target):
        result = runner.invoke(main, ["plugins", "list"])
    assert result.exit_code == 0
    assert "не существует" in result.output


def test_plugins_list_empty_directory(tmp_path: Path) -> None:
    """`gostforge plugins list` на пустой директории — соответствующее сообщение."""
    target = tmp_path / "plugins"
    target.mkdir()
    runner = CliRunner()
    with patch("gostforge.plugins.plugins_dir", return_value=target):
        result = runner.invoke(main, ["plugins", "list"])
    assert result.exit_code == 0
    assert "плагинов не найдено" in result.output


def test_plugins_list_loads_and_reports_check(tmp_path: Path) -> None:
    """`gostforge plugins list` загружает плагин и сообщает о новых кодах."""
    from gostforge.validator.engine import _registry

    target = tmp_path / "plugins"
    target.mkdir()
    (target / "ext.py").write_text(
        "from gostforge.validator.engine import register\n"
        "\n"
        "@register('Z.97')\n"
        "def check_z97(document, profile):\n"
        "    return []\n",
        encoding="utf-8",
    )

    _registry.pop("Z.97", None)
    sys.modules.pop("gostforge_plugin_ext", None)

    runner = CliRunner()
    with patch("gostforge.plugins.plugins_dir", return_value=target):
        result = runner.invoke(main, ["plugins", "list"])

    try:
        assert result.exit_code == 0
        assert "ext.py" in result.output
        assert "Z.97" in result.output
        assert "Найдено файлов: 1" in result.output
    finally:
        _registry.pop("Z.97", None)
        sys.modules.pop("gostforge_plugin_ext", None)
