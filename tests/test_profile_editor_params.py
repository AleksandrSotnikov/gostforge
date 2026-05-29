"""Тесты редактора `checks[code].params` и обзора `sections_template`.

Раньше UI редактора профиля показывал только enabled/severity у каждой
проверки, и пользователь не мог через UI поменять, например,
`R.04.params.min_length` или `R.15.params.timeout`. Теперь у каждой
проверки с непустым `params` появляется expander с динамическим UI.

`sections_template` — read-only (полноценный редактор требует много
работы, а большинству пользователей хватает наследования от базового
профиля).
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")


def test_profile_editor_renders_with_check_params() -> None:
    """`render_profile_editor` без exceptions при наличии params у проверок."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string(
        "from gostforge.web.profile_editor import render_profile_editor\nrender_profile_editor()\n"
    )
    at.run(timeout=90)
    assert not at.exception, [str(e) for e in at.exception]


def test_edit_check_params_handles_int_bool_str_list() -> None:
    """`_edit_check_params` подбирает widget по типу значения и мутирует params на месте.

    Без AppTest — функция не требует Streamlit-контекста для
    структурного теста: проверяем, что она не падает на разных
    типах данных в `params`. (Виджеты сами рисуют — мы тестируем
    устойчивость по типам.)
    """
    from streamlit.testing.v1 import AppTest

    # Прогоняем через AppTest, чтобы у st был контекст. Подкладываем
    # тестовый params и проверяем, что виджеты возникают.
    script = """
from gostforge.web.profile_editor import _edit_check_params
params = {
    "min_length": 15,        # int
    "require_year": True,    # bool
    "name": "test",          # str
    "ratio": 0.75,           # float
    "headings": ["A", "B"],  # list[str]
}
_edit_check_params("X.01", params, prefix="t")
"""
    at = AppTest.from_string(script)
    at.run(timeout=30)
    assert not at.exception, [str(e) for e in at.exception]
    # Должны появиться 5 widgets:
    # number_input (int) + checkbox (bool) + text_input (str) +
    # number_input (float) + text_area (list[str]).
    n_widgets = len(at.number_input) + len(at.checkbox) + len(at.text_input) + len(at.text_area)
    assert n_widgets >= 5, f"Ожидалось ≥5 widgets, получено {n_widgets}"


def test_edit_check_params_empty_dict_shows_caption() -> None:
    """Если params пуст — выводится caption, без виджетов."""
    from streamlit.testing.v1 import AppTest

    script = """
from gostforge.web.profile_editor import _edit_check_params
_edit_check_params("Y.01", {}, prefix="t")
"""
    at = AppTest.from_string(script)
    at.run(timeout=30)
    assert not at.exception
    # caption «У этой проверки нет параметров.» — без других виджетов.
    captions = [c.value for c in at.caption]
    assert any("параметров" in c.lower() for c in captions)


def test_view_sections_template_renders_existing_sections() -> None:
    """`_view_sections_template` показывает каждую секцию профиля."""
    from streamlit.testing.v1 import AppTest

    script = """
from gostforge.web.profile_editor import _view_sections_template
data = {
    "sections_template": [
        {"name": "Титульный лист", "type": "title", "page_numbering": {"visible": False}},
        {"name": "Основная часть", "type": "main", "page_numbering": {"visible": True}},
    ]
}
_view_sections_template(data)
"""
    at = AppTest.from_string(script)
    at.run(timeout=30)
    assert not at.exception, [str(e) for e in at.exception]
    # Должно быть 2 expander-а с названиями секций.
    expander_labels = [e.label for e in at.expander]
    assert any("Титульный лист" in lbl for lbl in expander_labels), (
        f"Не нашли expander «Титульный лист»: {expander_labels}"
    )
    assert any("Основная часть" in lbl for lbl in expander_labels)


def test_view_sections_template_empty_shows_info() -> None:
    """Без sections_template выводится `st.info` с пояснением."""
    from streamlit.testing.v1 import AppTest

    script = """
from gostforge.web.profile_editor import _view_sections_template
_view_sections_template({})
"""
    at = AppTest.from_string(script)
    at.run(timeout=30)
    assert not at.exception
    infos = [i.value for i in at.info]
    assert any("sections_template" in i for i in infos)


def test_profile_editor_has_sections_template_tab() -> None:
    """В редакторе профиля 9 вкладок (добавилась «Шаблон секций»)."""
    import inspect

    from gostforge.web import profile_editor

    source = inspect.getsource(profile_editor.render_profile_editor)
    assert '"Шаблон секций"' in source, "В render_profile_editor нет вкладки «Шаблон секций»"
