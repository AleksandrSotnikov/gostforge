"""Страница «Документация» — встроенный просмотр docs/*.md."""

from __future__ import annotations


def page() -> None:
    from gostforge.web.docs_viewer import render_docs_viewer

    render_docs_viewer()
