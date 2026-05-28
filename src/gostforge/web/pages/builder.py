"""Страница «Конструктор» — сборка работы из блоков.

На Этапе 1 — одна страница, оборачивает `builder_editor.render_interactive_builder`.
В Этапе 2 будет разрезано на 4 подстраницы (Структура / Контент / Проверка
/ Экспорт) внутри `web.pages.builder/` подпакета.
"""

from __future__ import annotations


def page() -> None:
    from gostforge.web.builder_editor import render_interactive_builder

    render_interactive_builder()
