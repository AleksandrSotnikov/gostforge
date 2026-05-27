"""Тесты стартовой страницы «Главная» (dashboard) Streamlit-UI.

Виджеты напрямую не дёргаем — проверяем, что render_dashboard
вызываемо, и что headless-рендер через AppTest проходит без
исключений и рисует заголовок.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.dashboard import render_dashboard


def test_render_dashboard_callable() -> None:
    """Функция импортируется и является вызываемой (smoke)."""
    assert callable(render_dashboard)


def test_dashboard_renders_headless() -> None:
    """Headless-рендер через AppTest: без исключений и с заголовком.

    AppTest.from_function теряет глобал ``st`` для модульных функций,
    поэтому используем from_string с маленьким драйвером.
    """
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string(
        "from gostforge.web.dashboard import render_dashboard\nrender_dashboard()\n"
    )
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    assert at.title  # заголовок есть
