"""Страница «Редактор профиля»."""

from __future__ import annotations


def page() -> None:
    from gostforge.web.profile_editor import render_profile_editor

    render_profile_editor()
