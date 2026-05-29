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
    """Каждый модуль в `web.pages` импортируется и имеет callable `page`.

    Конструктор — это подпакет с 4 страницами (structure / content /
    validation / export); каждая отдельный URL.
    """
    from gostforge.web.pages import (
        docs,
        history,
        home,
        normocontrol,
        profile_editor,
        profile_manager,
    )
    from gostforge.web.pages.builder import content, export, structure, validation

    modules = (
        home,
        normocontrol,
        profile_editor,
        profile_manager,
        history,
        docs,
        structure,
        content,
        validation,
        export,
    )
    for module in modules:
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


def test_builder_subpages_render_without_exceptions() -> None:
    """Каждая из 4 подстраниц Конструктора рендерится без исключений.

    Регресс на баг (этап 2A первой итерации), когда `_common_sidebar`
    дважды вызывал `_render_state_persistence_sidebar` — один раз
    напрямую, второй — внутри `_render_sidebar_metadata`. Из-за этого
    Streamlit падал с StreamlitDuplicateElementKey('builder_undo'),
    и main-area страницы оставалась пустой.
    """
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    expected_titles = {
        "structure": "Структура работы",
        "content": "Содержимое раздела",
        "validation": "Проверка",
        "export": "Экспорт",
    }
    for name, expected_title in expected_titles.items():
        at = AppTest.from_string(f"from gostforge.web.pages.builder.{name} import page\npage()\n")
        at.run(timeout=60)
        assert not at.exception, f"builder/{name}.page() упала с: {[str(e) for e in at.exception]}"
        titles = [t.value for t in at.title]
        assert expected_title in titles, (
            f"builder/{name} не отрисовала заголовок «{expected_title}»; были: {titles}"
        )


def test_profile_manager_page_renders_without_exceptions() -> None:
    """«Управление профилями» рендерится — список + загрузка YAML."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.profile_manager import page\npage()\n")
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    titles = [t.value for t in at.title]
    assert "Управление профилями" in titles, f"Ожидался заголовок, были: {titles}"
    # У страницы есть две секции: список установленных + загрузка YAML.
    subheaders = [s.value for s in at.subheader]
    assert any("Установленные" in s for s in subheaders), (
        f"Нет секции «Установленные»: {subheaders}"
    )
    assert any("Загрузить YAML" in s for s in subheaders), (
        f"Нет секции «Загрузить YAML»: {subheaders}"
    )


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
    # 5 верхнеуровневых страниц + 1 «Управление профилями» + 4 подстраницы
    # Конструктора = 10.
    assert len(paths) == 10, f"Ожидалось 10 страниц, найдено {len(paths)}: {paths}"
    assert len(set(paths)) == len(paths), f"Дубли URL pathname: {paths}"
    # Подстраницы конструктора — отдельные URL.
    assert {"builder-structure", "builder-content", "builder-validation", "builder-export"} <= set(
        paths
    )
    # «Управление профилями» отделено от «Редактора профиля».
    assert {"profile-editor", "profile-manager"} <= set(paths)
