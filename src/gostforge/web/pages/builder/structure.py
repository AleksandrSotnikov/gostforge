"""Конструктор: вкладка «Структура» — дерево разделов и шаблоны.

Показывает прогресс работы, чек-лист готовности, оглавление-превью,
дерево разделов с действиями (↑↓ / дублировать / удалить), кнопки
вставки шаблонов разделов (Введение/Заключение/Приложение/...) и
bulk-операции.
"""

from __future__ import annotations

import streamlit as st

from gostforge.web.pages.builder import _common_setup, _common_sidebar


def page() -> None:
    _common_setup()
    _common_sidebar()

    from gostforge.web.builder_editor import (
        _render_bulk_operations_sidebar,
        _render_progress_panel,
        _render_readiness_panel,
        _render_section_templates_sidebar,
        _render_section_tree,
        _render_toc_preview_panel,
    )

    st.title("Структура работы")
    st.caption(
        "Сборка скелета: добавляйте разделы и подразделы, расставляйте порядок. "
        "Шаблоны разделов (Введение / Заключение / Приложение) — в sidebar. "
        "Когда структура готова, переходите к «Содержимое» для наполнения."
    )

    _render_progress_panel()
    _render_readiness_panel()
    _render_toc_preview_panel()
    _render_section_tree()
    # Шаблоны разделов и bulk-операции живут в sidebar по историческим
    # причинам — функции сами добавляют свои секции через st.sidebar.
    _render_section_templates_sidebar()
    _render_bulk_operations_sidebar()
