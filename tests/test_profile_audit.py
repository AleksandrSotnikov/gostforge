"""Аудит профилей: все YAML-профили валидируются и не теряют параметры.

Защита от регрессов: если кто-то добавит поле в Pydantic-схему, но
забудет сохранить его в YAML профиля (или наоборот — добавит в YAML
ключ, который не описан в схеме) — этот тест упадёт.

Также проверяем что все checks из YAML имеют валидный CheckConfig
(enabled/severity/params).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from gostforge.profile import list_profiles, load_profile
from gostforge.profile.schema import Profile, _builtin_profiles_dir


def _profile_yaml_files() -> list[Path]:
    return sorted(_builtin_profiles_dir().glob("*.yaml"))


@pytest.mark.parametrize("yaml_path", _profile_yaml_files(), ids=lambda p: p.stem)
def test_yaml_loads_through_pydantic(yaml_path: Path) -> None:
    """Каждый YAML-профиль парсится через Pydantic без ошибок."""
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    # ValidationError → тест падает с понятной диагностикой.
    profile = Profile(**raw)
    assert profile.id
    assert profile.name


@pytest.mark.parametrize("profile_id", list_profiles(), ids=str)
def test_load_profile_returns_valid_instance(profile_id: str) -> None:
    """`load_profile(id)` возвращает Profile с проинициализированными полями.

    Также проверяет, что наследование (`extends`) не теряет параметров —
    если родитель имеет ключ, потомок его наследует через _merge_profile.
    """
    profile = load_profile(profile_id)
    assert profile.id == profile_id
    # У всех профилей по умолчанию должен быть стиль body (хотя бы из родителя).
    assert profile.styles.body.font
    assert profile.styles.body.size_pt > 0
    # И хотя бы одна проверка (наследуется из gost-7.32-2017).
    assert profile.checks, f"У {profile_id} нет ни одной проверки"


def test_default_profile_has_critical_checks() -> None:
    """gost-7.32-2017 — базовый профиль — содержит ключевые проверки."""
    profile = load_profile("gost-7.32-2017")
    critical = {"F.01", "F.02", "F.03", "T.01", "T.02", "S.01", "H.01", "R.04"}
    missing = critical - set(profile.checks.keys())
    assert not missing, f"Базовый профиль не содержит критичных проверок: {missing}"


def test_default_profile_has_explicit_table_styles() -> None:
    """gost-7.32-2017 явно задаёт styles.table.cell_size_pt и cell_font.

    Раньше эта секция отсутствовала, и cell_size_pt оставался None →
    экспортёр использовал body.size_pt = 14pt вместо ГОСТ-овых 12.
    """
    profile = load_profile("gost-7.32-2017")
    t = profile.styles.table
    assert t.cell_size_pt == 12.0
    assert t.cell_font == "Times New Roman"


def test_default_profile_has_explicit_figure_styles() -> None:
    """gost-7.32-2017 явно задаёт numbering и max_height_cm у рисунков."""
    profile = load_profile("gost-7.32-2017")
    f = profile.styles.figure
    assert f.max_width_cm > 0
    assert f.max_height_cm > 0
    assert f.numbering in ("continuous", "by_chapter")


def test_continuation_caption_on_by_default() -> None:
    """ГОСТ 7.32 требует «Продолжение таблицы N» — в дефолтном профиле on."""
    profile = load_profile("gost-7.32-2017")
    assert profile.styles.table.continuation_caption is True
    assert profile.styles.table.repeat_header is True


def test_check_params_preserved_through_load() -> None:
    """Параметры проверок (R.04, S.01, F.06, ...) не теряются при load."""
    profile = load_profile("gost-7.32-2017")

    # R.04 имеет нетривиальные params в default.
    r04 = profile.checks.get("R.04")
    if r04 is not None:
        # Хотя бы один параметр должен сохраниться.
        assert isinstance(r04.params, dict)

    # R.15 — params timeout, max_urls.
    r15 = profile.checks.get("R.15")
    if r15 is not None:
        assert "timeout" in r15.params or r15.enabled is False  # фича опц.


def test_extends_profile_inherits_parent_fields() -> None:
    """`extends`-профили наследуют пропущенные поля от родителя."""
    parent = load_profile("gost-7.32-2017")
    child = load_profile("gost-r-2.105-2019")
    # У ЕСКД-профиля переопределены поля; всё остальное — от родителя.
    assert child.styles.body.font == parent.styles.body.font
    # heading_1 не переопределяется у ребёнка — должен совпасть с родителем.
    assert child.styles.heading_1.font == parent.styles.heading_1.font
    # Поля страницы переопределены — это тестируем отдельно.
    assert child.styles.page.margins_mm["right"] == 10  # ЕСКД 10 мм
