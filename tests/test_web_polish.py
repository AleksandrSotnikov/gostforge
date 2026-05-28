"""Тесты UX-полировки (этап 3 multi-page рефакторинга).

* Onboarding-баннер на Главной (скрывается кнопкой «Скрыть подсказку»,
  состояние живёт в session_state).
* Breadcrumb (caption «📍 Раздел N / M ...») на странице
  «Содержимое раздела» — показывает текущую позицию в иерархии.
* Primary-кнопки (`type="primary"`) у главных действий — экспорт,
  скачать .docx.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")


def test_home_shows_onboarding_banner_by_default() -> None:
    """Главная страница по умолчанию показывает onboarding-баннер."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.home import page\npage()\n")
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    markdown_texts = [m.value for m in at.markdown]
    assert any("👋 С чего начать" in t for t in markdown_texts), (
        f"Onboarding-баннер не отрисован; markdown: {[t[:80] for t in markdown_texts[:10]]}"
    )
    # Должна быть кнопка скрытия.
    button_labels = [b.label for b in at.button]
    assert "Скрыть подсказку" in button_labels, f"Нет кнопки скрытия: {button_labels}"


def test_home_onboarding_hides_after_dismiss() -> None:
    """После set `home_onboarding_dismissed` баннер не показывается."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.home import page\npage()\n")
    at.session_state["home_onboarding_dismissed"] = True
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    markdown_texts = [m.value for m in at.markdown]
    assert not any("👋 С чего начать" in t for t in markdown_texts), (
        "Onboarding-баннер не должен показываться после dismiss"
    )


def test_content_page_shows_breadcrumb_when_sections_exist() -> None:
    """Страница «Содержимое» показывает breadcrumb с активным разделом."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.content import page\npage()\n")
    # Подкладываем state с одним разделом.
    at.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "s1",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "abc"}],
                "subsections": [],
            }
        ],
        "active_section_index": 0,
    }
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    captions = [c.value for c in at.caption]
    breadcrumb_found = any("📍 Раздел" in c and "Введение" in c for c in captions)
    assert breadcrumb_found, f"Breadcrumb «📍 Раздел ... Введение» не найден; captions: {captions}"


def test_export_primary_button_present() -> None:
    """На странице «Экспорт» есть кнопка «Сгенерировать .docx» (primary).

    `_render_generate_button` гейтит кнопку наличием заголовка работы,
    поэтому подкладываем минимальный state.
    """
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.export import page\npage()\n")
    at.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "s1",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "x"}],
                "subsections": [],
            }
        ],
        "active_section_index": 0,
    }
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    button_labels = [b.label for b in at.button]
    assert "Сгенерировать .docx" in button_labels, f"Нет кнопки экспорта: {button_labels}"


def test_content_page_has_help_block() -> None:
    """На странице «Содержимое» свёрнут help-блок «Что доступно»."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.content import page\npage()\n")
    at.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [{"id": "s1", "heading": "Глава", "blocks": [], "subsections": []}],
        "active_section_index": 0,
    }
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    expander_labels = [e.label for e in at.expander]
    help_found = any("Что доступно" in lbl for lbl in expander_labels)
    assert help_found, f"Help-блок не найден; expanders: {expander_labels}"


def test_content_page_exposes_full_block_palette() -> None:
    """На странице «Содержимое» доступны все 6 типов блоков (+Параграф/+Таблица/…).

    Регресс на случай, если кто-то частично спрячет add_block_buttons.
    """
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.content import page\npage()\n")
    at.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [{"id": "s1", "heading": "Глава", "blocks": [], "subsections": []}],
        "active_section_index": 0,
    }
    at.run(timeout=60)
    button_labels = {b.label for b in at.button}
    expected = {"+ Параграф", "+ Таблица", "+ Рисунок", "+ Список", "+ Формула", "+ Оглавление"}
    missing = expected - button_labels
    assert not missing, f"Не хватает кнопок добавления блока: {missing}"


def test_content_page_exposes_inline_element_buttons_inside_paragraph() -> None:
    """Внутри параграфа доступны inline-элементы: + Текст / + Формула / + Ссылка / + Цитата."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")

    at = AppTest.from_string("from gostforge.web.pages.builder.content import page\npage()\n")
    at.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "s1",
                "heading": "Глава",
                "blocks": [{"kind": "paragraph", "text": "abc"}],
                "subsections": [],
            }
        ],
        "active_section_index": 0,
    }
    at.run(timeout=60)
    button_labels = {b.label for b in at.button}
    expected = {"+ Текст", "+ Формула", "+ Ссылка", "+ Цитата"}
    missing = expected - button_labels
    assert not missing, f"Не хватает inline-кнопок: {missing}"


def test_structure_page_has_help_block() -> None:
    """На странице «Структура» свёрнут help-блок «Что доступно»."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")
    at = AppTest.from_string("from gostforge.web.pages.builder.structure import page\npage()\n")
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    expander_labels = [e.label for e in at.expander]
    assert any("Что доступно" in lbl for lbl in expander_labels), (
        f"Help-блок не найден; expanders: {expander_labels}"
    )


def test_validation_page_has_help_block() -> None:
    """На странице «Проверка» свёрнут help-блок «Что доступно»."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")
    at = AppTest.from_string("from gostforge.web.pages.builder.validation import page\npage()\n")
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    expander_labels = [e.label for e in at.expander]
    assert any("Что доступно" in lbl for lbl in expander_labels), (
        f"Help-блок не найден; expanders: {expander_labels}"
    )


def test_export_page_has_help_block() -> None:
    """На странице «Экспорт» свёрнут help-блок «Что доступно»."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")
    at = AppTest.from_string("from gostforge.web.pages.builder.export import page\npage()\n")
    at.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "s1",
                "heading": "Глава",
                "blocks": [{"kind": "paragraph", "text": "x"}],
                "subsections": [],
            }
        ],
        "active_section_index": 0,
    }
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    expander_labels = [e.label for e in at.expander]
    assert any("Что доступно" in lbl for lbl in expander_labels), (
        f"Help-блок не найден; expanders: {expander_labels}"
    )


def test_normocontrol_page_has_help_block() -> None:
    """На странице «Нормоконтроль» свёрнут help-блок «Что доступно».

    Помогает новичку: до загрузки файла видны только uploader + info,
    непонятно, что появится после. Help-блок описывает 4 вкладки и
    отчёты.
    """
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("AppTest недоступен")
    at = AppTest.from_string("from gostforge.web.pages.normocontrol import page\npage()\n")
    at.run(timeout=60)
    assert not at.exception, [str(e) for e in at.exception]
    expander_labels = [e.label for e in at.expander]
    assert any("Что доступно" in lbl for lbl in expander_labels), (
        f"Help-блок не найден; expanders: {expander_labels}"
    )
