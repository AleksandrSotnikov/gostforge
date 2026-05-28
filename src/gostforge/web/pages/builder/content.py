"""Конструктор: вкладка «Содержимое» — редактор активного раздела.

Здесь пользователь добавляет блоки (параграф, таблица, рисунок,
формула, список), редактирует run-ы внутри параграфов
(жирный/курсив/inline-формула/cross-ref/цитата), управляет
подразделами 2-3 уровней.

Активный раздел выбирается на странице «Структура» (через
``state["active_section_index"]``), но для быстрого переключения
здесь же показываем dropdown.
"""

from __future__ import annotations

import streamlit as st

from gostforge.web.pages.builder import _common_setup, _common_sidebar


def page() -> None:
    _common_setup()
    _common_sidebar()

    from gostforge.web.builder_editor import (
        _get_state,
        _render_active_section_editor,
    )

    st.title("Содержимое раздела")
    state = _get_state()
    sections = state.get("sections") or []
    if not sections:
        st.info(
            "Сначала создайте хотя бы один раздел на странице «Структура» — "
            "добавьте кнопкой «+ Раздел» или вставьте готовый шаблон."
        )
        return

    # Быстрый селектор активного раздела — для случая, когда пользователь
    # пришёл на эту страницу прямо по URL (минуя «Структуру»).
    idx = int(state.get("active_section_index", 0) or 0)
    if idx < 0 or idx >= len(sections):
        idx = 0
    options = list(range(len(sections)))
    new_idx = st.selectbox(
        "Активный раздел",
        options=options,
        index=options.index(idx),
        format_func=lambda i: f"{i + 1}. {sections[i].get('heading') or '(без названия)'}",
        key="content_active_section",
        help="Переключайте раздел, не переходя обратно на «Структуру».",
    )
    if new_idx != idx:
        state["active_section_index"] = int(new_idx)
        st.rerun()

    _render_active_section_editor()
