"""Тесты multi-page навигации Streamlit (`st.navigation` + `st.Page`).

После перехода на multi-page каждый режим — отдельная страница со своим
URL pathname (`/?page=home` / `/?page=normocontrol` и т. д.). Здесь
проверяем, что каркас работает, страницы импортируются и URL pathname-ы
уникальны.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")


def test_all_page_modules_importable() -> None:
    """Каждый модуль в `web.pages` импортируется и имеет callable `page`."""
    from gostforge.web.pages import (
        builder,
        docs,
        history,
        home,
        normocontrol,
        profile_editor,
    )

    for module in (home, normocontrol, builder, profile_editor, history, docs):
        assert hasattr(module, "page"), f"{module.__name__} должен иметь функцию page()"
        assert callable(module.page)


def test_app_renders_navigation_without_exceptions() -> None:
    """`render()` собирает st.navigation без ошибок и страницы регистрируются."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.app import render\nrender()\n")
    at.run(timeout=90)
    assert not at.exception, [str(e) for e in at.exception]
    # На дефолтной странице (Главная) есть заголовок дашборда.
    assert at.title


def test_navigation_url_paths_are_unique() -> None:
    """URL pathname-ы уникальны — иначе Streamlit падает с ошибкой коллизии."""
    # Эта проверка — структурная: смотрим прямо в app.py. URL pathname-ы
    # перечислены как аргументы `url_path=` в `st.Page(...)`. Если в коде
    # окажутся дубли — `render()` упадёт на ребое выше.
    import inspect

    from gostforge.web import app

    source = inspect.getsource(app.render)
    # Все url_path= аргументы.
    import re

    paths = re.findall(r'url_path="([^"]+)"', source)
    assert len(paths) == 6, f"Ожидалось 6 страниц, найдено {len(paths)}: {paths}"
    assert len(set(paths)) == len(paths), f"Дубли URL pathname: {paths}"
