"""Страница «Нормоконтроль» — проверка .docx по выбранному профилю."""

from __future__ import annotations


def page() -> None:
    """Нормоконтроль: sidebar (выбор профиля) + main (загрузка, проверка)."""
    from gostforge.profile import list_profiles
    from gostforge.web.app import _render_main, _render_sidebar

    profiles = list_profiles()
    if not profiles:
        import streamlit as st

        st.error("Не найдено ни одного профиля. Проверьте директорию profiles/.")
        return
    profile_id = _render_sidebar(profiles)
    _render_main(profile_id)
