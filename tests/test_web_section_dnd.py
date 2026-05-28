"""Тесты drag-and-drop переупорядочивания разделов.

Roadmap Q2/2026: «Drag-and-drop порядка разделов и блоков (требует
streamlit-sortables)». Пока сделан DnD для разделов; для блоков —
следующая итерация.

Сама библиотека streamlit-sortables — JS-компонент, который в
AppTest не отрисовывается. Поэтому тестируем:

* что toggle «Drag-and-drop разделов» появляется на странице
  «Структура»;
* что после включения toggle-а классические кнопки ↑/↓/⎘/✕
  исчезают и появляется select-box для выбора активного раздела;
* что переключение toggle-а сохраняется в session_state.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")


def _build_state_with_sections(n: int) -> dict[str, object]:
    return {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": f"s{i}",
                "heading": f"Раздел {i}",
                "blocks": [],
                "subsections": [],
            }
            for i in range(n)
        ],
        "active_section_index": 0,
    }


def test_structure_page_shows_dnd_toggle() -> None:
    """На странице «Структура» виден toggle «Drag-and-drop разделов»."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.structure import page\npage()\n")
    at.session_state["builder_state"] = _build_state_with_sections(3)
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    toggle_labels = [t.label for t in at.toggle]
    assert any("Drag-and-drop разделов" in lbl for lbl in toggle_labels), (
        f"Toggle DnD не найден; toggles: {toggle_labels}"
    )


def test_structure_page_dnd_replaces_buttons_with_select() -> None:
    """После включения toggle-а кнопки ↑/↓/⎘/✕ исчезают, появляется select-box."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.structure import page\npage()\n")
    at.session_state["builder_state"] = _build_state_with_sections(3)
    at.run(timeout=60)
    # Сначала классический режим: видим стрелки.
    button_labels_off = [b.label for b in at.button]
    assert "↑" in button_labels_off, "В классике должны быть кнопки ↑"

    # Включаем DnD.
    dnd_toggles = [t for t in at.toggle if "Drag-and-drop разделов" in t.label]
    assert dnd_toggles, "Toggle DnD не найден"
    dnd_toggles[0].set_value(True)
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]

    # В DnD-режиме кнопок ↑/↓ нет.
    button_labels_on = [b.label for b in at.button]
    assert "↑" not in button_labels_on, "В DnD-режиме стрелки должны исчезнуть"
    # И есть select-box «Активный раздел».
    selectbox_labels = [s.label for s in at.selectbox]
    assert any("Активный раздел" in lbl for lbl in selectbox_labels), (
        f"Select-box «Активный раздел» не найден; selectboxes: {selectbox_labels}"
    )


def test_reorder_sections_by_dnd_items_simple() -> None:
    """`_reorder_sections_by_dnd_items` переставляет sections по новому порядку id."""
    from gostforge.web.builder_editor import _reorder_sections_by_dnd_items

    sections = [
        {"id": "a", "heading": "Введение"},
        {"id": "b", "heading": "Глава 1"},
        {"id": "c", "heading": "Заключение"},
    ]
    sorted_items = ["#c: Заключение", "#a: Введение", "#b: Глава 1"]
    out = _reorder_sections_by_dnd_items(sections, sorted_items)
    assert out is not None
    assert [s["id"] for s in out] == ["c", "a", "b"]


def test_reorder_sections_by_dnd_items_returns_none_on_unknown_id() -> None:
    """При неизвестном id — None (нестабильный матчинг)."""
    from gostforge.web.builder_editor import _reorder_sections_by_dnd_items

    sections = [{"id": "a", "heading": "Один"}, {"id": "b", "heading": "Два"}]
    sorted_items = ["#a: Один", "#zzz: Левый"]
    assert _reorder_sections_by_dnd_items(sections, sorted_items) is None


def test_reorder_sections_by_dnd_items_returns_none_on_count_mismatch() -> None:
    """При расхождении количества — None (защита от потери разделов)."""
    from gostforge.web.builder_editor import _reorder_sections_by_dnd_items

    sections = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    sorted_items = ["#a: x", "#b: y"]  # на один меньше
    assert _reorder_sections_by_dnd_items(sections, sorted_items) is None


def test_reorder_sections_by_dnd_items_returns_none_on_bad_format() -> None:
    """Невалидный формат строки — None."""
    from gostforge.web.builder_editor import _reorder_sections_by_dnd_items

    sections = [{"id": "a"}, {"id": "b"}]
    assert _reorder_sections_by_dnd_items(sections, ["no-hash-prefix", "#a: x"]) is None
    assert _reorder_sections_by_dnd_items(sections, ["#noseparator", "#a: x"]) is None


def test_section_dnd_state_persists_in_session() -> None:
    """`section_dnd_enabled` сохраняется в state при переключении toggle."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.structure import page\npage()\n")
    at.session_state["builder_state"] = _build_state_with_sections(2)
    at.run(timeout=60)
    # До включения toggle-а флаг в state — False/отсутствует.
    state = at.session_state["builder_state"]
    assert not state.get("section_dnd_enabled", False)
    # Включаем toggle.
    dnd_toggles = [t for t in at.toggle if "Drag-and-drop разделов" in t.label]
    dnd_toggles[0].set_value(True)
    at.run(timeout=60)
    # Теперь флаг True.
    state = at.session_state["builder_state"]
    assert state.get("section_dnd_enabled") is True
