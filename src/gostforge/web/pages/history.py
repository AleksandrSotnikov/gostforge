"""Страница «История» — submission-ы из локальной БД."""

from __future__ import annotations


def page() -> None:
    from gostforge.web.history_viewer import render_history_viewer

    render_history_viewer()
