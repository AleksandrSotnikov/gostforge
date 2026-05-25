"""Тесты загрузки профилей."""

from gostforge.profile import list_profiles, load_profile


def test_base_profile_loads() -> None:
    p = load_profile("gost-7.32-2017")
    assert p.id == "gost-7.32-2017"
    assert p.styles.body.font == "Times New Roman"
    assert p.styles.body.size_pt == 14
    assert "F.01" in p.checks


def test_inherited_profile_overrides_body_size() -> None:
    p = load_profile("example-department")
    assert p.id == "example-department"
    # Унаследовано от родителя
    assert "F.01" in p.checks
    # Переопределено в дочернем
    assert p.styles.body.size_pt == 12


def test_list_profiles_contains_base() -> None:
    profiles = list_profiles()
    assert "gost-7.32-2017" in profiles


def test_inheritance_keeps_unchanged_parent_styles() -> None:
    """Deep-merge: переопределение одного поля не должно ломать остальные."""
    child = load_profile("example-department")
    parent = load_profile("gost-7.32-2017")
    # Дочерний переопределил body.size_pt = 12, но остальные стили — родительские.
    assert child.styles.body.font == parent.styles.body.font
    assert child.styles.body.line_spacing == parent.styles.body.line_spacing
    assert child.styles.page.margins_mm == parent.styles.page.margins_mm
    # И проверки родителя должны быть унаследованы:
    assert "F.01" in child.checks
    assert child.checks["F.01"].enabled == parent.checks["F.01"].enabled


def test_inheritance_merges_check_params() -> None:
    """Параметры проверки, заданные у ребёнка, перебивают родительские."""
    child = load_profile("example-department")
    assert child.checks["T.02"].params["body_size"] == 12
    assert child.checks["T.02"].params["caption_size"] == 11


def test_gost_r_2_105_profile_loads() -> None:
    """Профиль ЕСКД наследует базовый и переопределяет геометрию и разделы."""
    p = load_profile("gost-r-2.105-2019")
    assert p.id == "gost-r-2.105-2019"
    assert p.extends == "gost-7.32-2017"
    # Переопределённые поля
    assert p.styles.page.margins_mm == {"top": 20.0, "right": 10.0, "bottom": 20.0, "left": 20.0}
    assert p.checks["F.06"].params["start_value"] == 2
    assert "Содержание" in p.checks["S.01"].params["required_headings"]
    # Унаследованные от базового
    assert p.styles.body.font == "Times New Roman"
    assert p.styles.body.size_pt == 14
    assert "F.01" in p.checks
