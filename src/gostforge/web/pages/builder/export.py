"""Конструктор: вкладка «Экспорт» — генерация финального .docx и других форматов.

`_render_generate_button` отвечает за:

* сборку state → Document → .docx через builder;
* PDF-превью через LibreOffice;
* экспорт в Markdown / HTML;
* опциональное применение автофиксов перед сборкой.
"""

from __future__ import annotations

import streamlit as st

from gostforge.web.pages.builder import _common_setup, _common_sidebar


def page() -> None:
    _common_setup()
    _common_sidebar()

    from gostforge.web.builder_editor import _render_generate_button

    st.title("Экспорт")
    st.caption(
        "Когда работа собрана и проверена — сгенерируйте файл в нужном формате. "
        "Перед экспортом можно применить автофиксы — они исправят безопасные "
        "ошибки оформления (двойные пробелы, прямые кавычки, кегль и т.д.)."
    )

    _render_generate_button()
