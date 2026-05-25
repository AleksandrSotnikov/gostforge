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
