"""Страница «Главная» — обзорный дашборд."""

from __future__ import annotations


def page() -> None:
    """Тонкая обёртка над `dashboard.render_dashboard` для st.Page."""
    from gostforge.web.dashboard import render_dashboard

    render_dashboard()
