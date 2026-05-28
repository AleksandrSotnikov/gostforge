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
