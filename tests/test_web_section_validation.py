"""Тесты UI-функций «Нормоконтроль раздела».

UI-секция работает с поля state["sections"][idx]["disabled_checks"] —
list[str]. ``["*"]`` = отключить все. UI-вызов рендерится в Streamlit;
здесь тестируем чистые помощники и интеграцию с _build_document_from_state.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import (
    _CHECK_CATEGORIES,
    _list_available_check_codes,
)


def test_list_available_check_codes_returns_registered() -> None:
    codes = _list_available_check_codes()
    assert codes  # хоть какие-то проверки зарегистрированы
    # Проверим что точно есть несколько известных.
    assert "F.01" in codes
    assert "T.01" in codes
    assert "H.01" in codes


def test_check_categories_cover_known_prefixes() -> None:
    """Все префиксы зарегистрированных кодов должны иметь
    человекочитаемый label в _CHECK_CATEGORIES."""
    codes = _list_available_check_codes()
    prefixes = {c[:2] for c in codes}
    unknown = prefixes - set(_CHECK_CATEGORIES.keys())
    assert not unknown, (
        f"Появились новые префиксы кодов без label-а: {sorted(unknown)}. "
        f"Добавьте их в _CHECK_CATEGORIES."
    )


def test_render_panel_importable() -> None:
    """Sidebar-функция импортируется (smoke без st.session_state)."""
    from gostforge.web.builder_editor import _render_section_validation_panel

    assert callable(_render_section_validation_panel)


# --- интеграция: state→builder→Document с disabled_checks ---


def test_state_with_disabled_checks_propagates_to_document() -> None:
    """state['sections'][i]['disabled_checks'] прокидывается в LogicalSection."""
    from gostforge.web.builder_editor import _build_document_from_state

    state = {
        "title": "Тест",
        "author": "И.И.",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "work_type": "coursework",
        "sections": [
            {
                "heading": "Титульный лист",
                "blocks": [{"kind": "paragraph", "text": "Текст"}],
                "disabled_checks": ["*"],
            },
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Актуальность."}],
            },
            {
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "references": ["Кнут. — М., 2007."],
                "disabled_checks": ["R.10", "R.11"],
            },
        ],
    }
    # _build_document_from_state ВНУТРИ зовёт builder.build() и export_docx
    # в tmp-файл — возвращает bytes. Нам этого достаточно для smoke:
    # если skip_checks/skip_all_checks не работают — будет KeyError или
    # ValueError на этапе сборки.
    data = _build_document_from_state(state)
    assert isinstance(data, bytes) and len(data) > 0


def test_state_with_specific_disabled_codes() -> None:
    """state['sections'][i]['disabled_checks'] = ['T.01', 'H.01']
    приводит к skip_checks вызову (не skip_all_checks)."""
    from gostforge.builder import work

    # Промежуточный smoke — собираем напрямую через builder API,
    # сверяем что disabled_checks попадает в LogicalSection.
    b = work("X", year=2026).section("Титул").paragraph("p").skip_checks("T.01", "H.01")
    doc = b.build()
    sec = doc.page_sections[0].content[0]
    assert hasattr(sec, "disabled_checks")
    assert "T.01" in sec.disabled_checks
    assert "H.01" in sec.disabled_checks
    assert "*" not in sec.disabled_checks  # specific, не wildcard
