# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты функции _apply_style_overrides в Streamlit-конструкторе.

UI-секцию (sidebar) проверяем только smoke-импортом — здесь
тестируется чистая функция применения overrides к Profile.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.profile import load_profile
from gostforge.web.builder_editor import _apply_style_overrides


def test_no_overrides_returns_original_profile() -> None:
    """Пустой dict — возвращается исходный профиль (без копирования)."""
    p = load_profile("gost-7.32-2017")
    result = _apply_style_overrides(p, {})
    assert result is p


def test_page_margins_overrides() -> None:
    p = load_profile("gost-7.32-2017")
    over = {"page_margins_mm": {"top": 25, "right": 12, "bottom": 22, "left": 35}}
    new_p = _apply_style_overrides(p, over)
    assert new_p.styles.page.margins_mm["top"] == 25
    assert new_p.styles.page.margins_mm["right"] == 12
    assert new_p.styles.page.margins_mm["bottom"] == 22
    assert new_p.styles.page.margins_mm["left"] == 35
    # Оригинал не тронут.
    assert p.styles.page.margins_mm["top"] == 20


def test_partial_margins_keep_others() -> None:
    """Override только некоторых полей — остальные берутся из профиля."""
    p = load_profile("gost-7.32-2017")
    over = {"page_margins_mm": {"top": 25}}
    new_p = _apply_style_overrides(p, over)
    assert new_p.styles.page.margins_mm["top"] == 25
    assert new_p.styles.page.margins_mm["right"] == 15  # default ГОСТ


def test_body_font_and_size_override() -> None:
    p = load_profile("gost-7.32-2017")
    over = {"body_font": "Arial", "body_size_pt": 12}
    new_p = _apply_style_overrides(p, over)
    assert new_p.styles.body.font == "Arial"
    assert new_p.styles.body.size_pt == 12


def test_empty_string_body_font_keeps_default() -> None:
    """Пустая строка не должна затирать font (UX-защита)."""
    p = load_profile("gost-7.32-2017")
    new_p = _apply_style_overrides(p, {"body_font": ""})
    assert new_p.styles.body.font == "Times New Roman"


def test_heading1_uppercase_override() -> None:
    p = load_profile("gost-7.32-2017")
    new_p = _apply_style_overrides(p, {"heading1_uppercase": False})
    assert new_p.styles.heading_1.uppercase is False


def test_heading1_color_override() -> None:
    p = load_profile("gost-7.32-2017")
    new_p = _apply_style_overrides(p, {"heading1_color": "FF0000"})
    assert new_p.styles.heading_1.color == "FF0000"


def test_heading1_spacing_overrides() -> None:
    p = load_profile("gost-7.32-2017")
    over = {"heading1_spacing_before_pt": 24, "heading1_spacing_after_pt": 18}
    new_p = _apply_style_overrides(p, over)
    assert new_p.styles.heading_1.spacing_before_pt == 24
    assert new_p.styles.heading_1.spacing_after_pt == 18


def test_bullet_char_override() -> None:
    p = load_profile("gost-7.32-2017")
    new_p = _apply_style_overrides(p, {"bullet_char": "•"})
    assert new_p.styles.lists.bullet_char == "•"


def test_ordered_format_override() -> None:
    p = load_profile("gost-7.32-2017")
    new_p = _apply_style_overrides(p, {"ordered_format": "{n}."})
    assert new_p.styles.lists.ordered_format == "{n}."


def test_table_border_style_override() -> None:
    p = load_profile("gost-7.32-2017")
    new_p = _apply_style_overrides(p, {"table_border_style": "double"})
    assert new_p.styles.table.border_style == "double"


def test_table_header_bold_override() -> None:
    p = load_profile("gost-7.32-2017")
    new_p = _apply_style_overrides(p, {"table_header_bold": False})
    assert new_p.styles.table.header_bold is False


def test_multiple_overrides_combine() -> None:
    """Все категории overrides применяются за один вызов."""
    p = load_profile("gost-7.32-2017")
    over = {
        "page_margins_mm": {"top": 25},
        "body_font": "Calibri",
        "heading1_uppercase": False,
        "bullet_char": "•",
        "table_border_style": "none",
    }
    new_p = _apply_style_overrides(p, over)
    assert new_p.styles.page.margins_mm["top"] == 25
    assert new_p.styles.body.font == "Calibri"
    assert new_p.styles.heading_1.uppercase is False
    assert new_p.styles.lists.bullet_char == "•"
    assert new_p.styles.table.border_style == "none"


def test_overrides_do_not_mutate_original_profile() -> None:
    """Оригинальный профиль не меняется (deep-copy внутри)."""
    p = load_profile("gost-7.32-2017")
    orig_font = p.styles.body.font
    orig_uppercase = p.styles.heading_1.uppercase
    _apply_style_overrides(p, {"body_font": "Arial", "heading1_uppercase": False})
    assert p.styles.body.font == orig_font
    assert p.styles.heading_1.uppercase == orig_uppercase


def test_render_section_importable() -> None:
    """Sidebar-функция импортируется (smoke)."""
    from gostforge.web.builder_editor import _render_style_overrides_section

    assert callable(_render_style_overrides_section)
