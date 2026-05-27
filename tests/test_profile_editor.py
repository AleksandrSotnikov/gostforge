"""Тесты редактора профиля форматирования (чистые helper-функции).

Streamlit-виджеты здесь не тестируются (нужен раннер), проверяется
логика преобразования/валидации/сохранения, на которую опирается UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from gostforge.profile import load_profile
from gostforge.profile.schema import Profile
from gostforge.web.profile_editor import (
    build_extends_profile_yaml,
    build_profile_yaml,
    delete_custom_profile,
    list_installed_custom_profiles,
    profile_to_data,
    render_profile_editor,
    save_profile_to_registry,
)


def test_module_exposes_render() -> None:
    assert callable(render_profile_editor)


def test_render_runs_headless_without_exception() -> None:
    """Полный рендер редактора прогоняется через AppTest без исключений."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("streamlit AppTest недоступен в этой версии")

    driver = (
        "from gostforge.web.profile_editor import render_profile_editor\nrender_profile_editor()\n"
    )
    at = AppTest.from_string(driver)
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.value for t in at.title] == ["Редактор профиля форматирования"]
    # Все группы параметров на месте: 8 верхних вкладок + 4 для заголовков.
    assert len(at.tabs) >= 12


def test_profile_to_data_roundtrip() -> None:
    prof = load_profile("gost-7.32-2017")
    data = profile_to_data(prof)
    assert data["id"] == "gost-7.32-2017"
    # data → Profile → совпадает с исходным
    assert Profile(**data).model_dump() == prof.model_dump()


def test_build_profile_yaml_reflects_edits() -> None:
    data = profile_to_data(load_profile("gost-7.32-2017"))
    data["id"] = "my-prof"
    data["styles"]["body"]["font"] = "Arial"
    data["styles"]["body"]["size_pt"] = 13.0
    data["styles"]["heading_1"]["uppercase"] = False
    yaml_text = build_profile_yaml(data)

    # YAML загружается обратно в валидный Profile с нашими правками.
    import yaml as _yaml

    reloaded = Profile(**_yaml.safe_load(yaml_text))
    assert reloaded.id == "my-prof"
    assert reloaded.styles.body.font == "Arial"
    assert reloaded.styles.body.size_pt == 13.0
    assert reloaded.styles.heading_1.uppercase is False


def test_build_profile_yaml_invalid_raises() -> None:
    data = profile_to_data(load_profile("gost-7.32-2017"))
    data["styles"]["body"]["alignment"] = "diagonal"  # не из Literal
    with pytest.raises(ValueError, match="валидаци"):
        build_profile_yaml(data)


def test_save_profile_to_registry_then_loadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(tmp_path / "reg.db"))
    data = profile_to_data(load_profile("gost-7.32-2017"))
    data["id"] = "kafedra-test"
    data["name"] = "Кафедральный (тест)"
    data["styles"]["body"]["size_pt"] = 12.0
    yaml_text = build_profile_yaml(data)

    saved_id = save_profile_to_registry(yaml_text, overwrite=False)
    assert saved_id == "kafedra-test"

    # Профиль читается через стандартный load_profile (db-first).
    loaded = load_profile("kafedra-test")
    assert loaded.name == "Кафедральный (тест)"
    assert loaded.styles.body.size_pt == 12.0


def test_save_profile_overwrite_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(tmp_path / "reg.db"))
    data = profile_to_data(load_profile("gost-7.32-2017"))
    data["id"] = "dup"
    yaml_text = build_profile_yaml(data)
    save_profile_to_registry(yaml_text, overwrite=False)
    # Повторная установка без overwrite — ошибка.
    with pytest.raises(ValueError):
        save_profile_to_registry(yaml_text, overwrite=False)
    # С overwrite — успех.
    assert save_profile_to_registry(yaml_text, overwrite=True) == "dup"


def test_build_extends_yaml_is_minimal_diff() -> None:
    import yaml as _yaml

    data = profile_to_data(load_profile("gost-7.32-2017"))
    data["id"] = "kaf-ext"
    data["name"] = "Кафедра (наследник)"
    data["styles"]["body"]["size_pt"] = 13.0  # единственное отличие
    yaml_text = build_extends_profile_yaml(data, "gost-7.32-2017")

    parsed = _yaml.safe_load(yaml_text)
    assert parsed["extends"] == "gost-7.32-2017"
    assert parsed["id"] == "kaf-ext"
    # В diff попало только изменённое поле, не весь styles.
    assert parsed["styles"] == {"body": {"size_pt": 13.0}}
    assert "checks" not in parsed  # проверки не трогали


def test_extends_profile_roundtrip_via_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(tmp_path / "reg.db"))
    base = load_profile("gost-7.32-2017")
    data = profile_to_data(base)
    data["id"] = "kaf-ext2"
    data["name"] = "Наследник 2"
    data["styles"]["body"]["font"] = "Arial"  # меняем шрифт
    yaml_text = build_extends_profile_yaml(data, "gost-7.32-2017")
    save_profile_to_registry(yaml_text, overwrite=False)

    loaded = load_profile("kaf-ext2")
    # Изменённое поле применилось…
    assert loaded.styles.body.font == "Arial"
    # …а неизменённые унаследованы от базового профиля.
    assert loaded.styles.body.size_pt == base.styles.body.size_pt
    assert loaded.styles.heading_1.uppercase == base.styles.heading_1.uppercase
    assert loaded.extends == "gost-7.32-2017"


def test_list_and_delete_custom_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOSTFORGE_DB_PATH", str(tmp_path / "reg.db"))
    assert list_installed_custom_profiles() == []

    data = profile_to_data(load_profile("gost-7.32-2017"))
    data["id"] = "kaf-1"
    data["name"] = "Кафедра 1"
    save_profile_to_registry(build_profile_yaml(data), overwrite=False)

    installed = list_installed_custom_profiles()
    ids = [p["id"] for p in installed]
    assert "kaf-1" in ids
    rec = next(p for p in installed if p["id"] == "kaf-1")
    assert rec["name"] == "Кафедра 1"

    # Удаление: True для существующего, False для отсутствующего.
    assert delete_custom_profile("kaf-1") is True
    assert delete_custom_profile("kaf-1") is False
    assert list_installed_custom_profiles() == []
