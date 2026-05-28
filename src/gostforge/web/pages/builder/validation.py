"""Конструктор: вкладка «Проверка» — live-нормоконтроль и импортированные сообщения.

Показывает:

* нарушения live-нормоконтроля для текущего state (сводка + детали с
  кликом «→ К разделу»);
* нарушения, найденные в .docx при импорте (если работа была загружена);
* комментарии рецензента из импортированного .docx.
"""

from __future__ import annotations

import streamlit as st

from gostforge.web.pages.builder import _common_setup, _common_sidebar


def page() -> None:
    _common_setup()
    _common_sidebar()

    from gostforge.web.builder_editor import (
        _render_import_violations_panel,
        _render_imported_comments_panel,
        _render_live_validation_panel,
    )

    st.title("Проверка")
    st.caption(
        "Live-нормоконтроль гоняется автоматически после каждой правки. "
        "Кнопка «→ К разделу» рядом с нарушением переключает вас на нужный "
        "раздел во вкладке «Содержимое»."
    )

    _render_import_violations_panel()
    _render_imported_comments_panel()
    _render_live_validation_panel()
