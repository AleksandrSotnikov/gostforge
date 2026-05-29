"""Тесты загрузчика пользовательских плагинов."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from gostforge.plugins import discover_plugin_files, load_plugins, plugins_dir


def test_plugins_dir_default_path() -> None:
    """``plugins_dir()`` возвращает разумный путь под текущую ОС."""
    d = plugins_dir()
    assert isinstance(d, Path)
    # На Linux/macOS — каталог .gostforge в домашней папке.
    # На Windows с заданным APPDATA — APPDATA/gostforge/plugins.
    if os.name == "nt" and os.environ.get("APPDATA"):
        assert "gostforge" in str(d)
        assert d.name == "plugins"
    else:
        assert d.name == "plugins"
        assert ".gostforge" in d.parts


def test_discover_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    """Пустая директория — пустой список."""
    assert discover_plugin_files(tmp_path) == []


def test_discover_nonexistent_directory(tmp_path: Path) -> None:
    """Несуществующая директория — пустой список без ошибки."""
    missing = tmp_path / "does_not_exist"
    assert discover_plugin_files(missing) == []


def test_discover_finds_python_files(tmp_path: Path) -> None:
    """``discover_plugin_files`` находит ``.py`` и игнорирует прочее."""
    (tmp_path / "a.py").write_text("# plugin a", encoding="utf-8")
    (tmp_path / "b.py").write_text("# plugin b", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a plugin", encoding="utf-8")
    (tmp_path / "sub").mkdir()  # подкаталог не должен попасть в результат

    files = discover_plugin_files(tmp_path)
    names = sorted(p.name for p in files)
    assert names == ["a.py", "b.py"]


def test_discover_ignores_underscored(tmp_path: Path) -> None:
    """Файлы с ведущим ``_`` (вспомогательные) пропускаются."""
    (tmp_path / "_helper.py").write_text("# private", encoding="utf-8")
    (tmp_path / "__init__.py").write_text("# init", encoding="utf-8")
    (tmp_path / "real.py").write_text("# real plugin", encoding="utf-8")

    files = discover_plugin_files(tmp_path)
    assert [p.name for p in files] == ["real.py"]


def test_load_plugin_registers_check(tmp_path: Path) -> None:
    """После ``load_plugins`` зарегистрированная в плагине проверка доступна."""
    from gostforge.validator.engine import _registry

    code = "Z.99"
    # Защитимся от уже зарегистрированного из другого теста.
    _registry.pop(code, None)
    sys.modules.pop("gostforge_plugin_my_dept", None)

    plugin = tmp_path / "my_dept.py"
    plugin.write_text(
        "from gostforge.validator.engine import register\n"
        "\n"
        "@register('Z.99')\n"
        "def check_z99(document, profile):\n"
        "    return []\n",
        encoding="utf-8",
    )

    loaded = load_plugins(tmp_path)
    try:
        assert "gostforge_plugin_my_dept" in loaded
        assert code in _registry
    finally:
        _registry.pop(code, None)
        sys.modules.pop("gostforge_plugin_my_dept", None)


def test_load_plugin_handles_import_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Плагин с синтаксической ошибкой не валит загрузку других плагинов."""
    from gostforge.validator.engine import _registry

    bad = tmp_path / "broken.py"
    bad.write_text("this is not valid python ===", encoding="utf-8")

    good = tmp_path / "good.py"
    good.write_text(
        "from gostforge.validator.engine import register\n"
        "\n"
        "@register('Z.98')\n"
        "def check_z98(document, profile):\n"
        "    return []\n",
        encoding="utf-8",
    )

    _registry.pop("Z.98", None)
    sys.modules.pop("gostforge_plugin_good", None)
    sys.modules.pop("gostforge_plugin_broken", None)

    with caplog.at_level("WARNING", logger="gostforge.plugins"):
        loaded = load_plugins(tmp_path)
    try:
        # Хороший плагин загрузился, плохой — нет.
        assert "gostforge_plugin_good" in loaded
        assert "gostforge_plugin_broken" not in loaded
        assert "Z.98" in _registry
        # Битый модуль не задержался в sys.modules.
        assert "gostforge_plugin_broken" not in sys.modules
        # В лог попало предупреждение.
        assert any("broken" in rec.message for rec in caplog.records)
    finally:
        _registry.pop("Z.98", None)
        sys.modules.pop("gostforge_plugin_good", None)


def test_load_plugins_empty_directory_returns_empty(tmp_path: Path) -> None:
    """``load_plugins`` на пустой/несуществующей директории не падает."""
    assert load_plugins(tmp_path) == []
    assert load_plugins(tmp_path / "missing") == []


def test_plugin_info_empty_directory(tmp_path: Path) -> None:
    """plugin_info на пустом каталоге: файлов нет, кодов нет, exists=True."""
    from gostforge.plugins import plugin_info

    info = plugin_info(tmp_path)
    assert info["directory"] == str(tmp_path)
    assert info["exists"] is True
    assert info["files"] == []
    assert info["added_codes"] == []


def test_plugin_info_reports_files_and_added_codes(tmp_path: Path) -> None:
    """plugin_info перечисляет .py-файлы и коды, добавленные плагином."""
    from gostforge.plugins import plugin_info
    from gostforge.validator.engine import _registry

    code = "Z.98"
    _registry.pop(code, None)
    sys.modules.pop("gostforge_plugin_dept2", None)
    plugin = tmp_path / "dept2.py"
    plugin.write_text(
        "from gostforge.validator.engine import register\n"
        "\n"
        "@register('Z.98')\n"
        "def check_z98(document, profile):\n"
        "    return []\n",
        encoding="utf-8",
    )
    try:
        info = plugin_info(tmp_path)
        assert "dept2.py" in info["files"]  # type: ignore[operator]
        assert "Z.98" in info["added_codes"]  # type: ignore[operator]
    finally:
        _registry.pop(code, None)
        sys.modules.pop("gostforge_plugin_dept2", None)
