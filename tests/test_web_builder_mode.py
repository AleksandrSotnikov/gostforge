"""Smoke-тесты для режима «Конструктор» в Streamlit-UI.

Полноценный e2e Streamlit-приложения требует отдельного раннера и
контекста сессии (см. test_web_smoke.py). Сборка болванок без streamlit
покрыта `test_builder_templates.py`. Здесь же мы только проверяем, что
функция `_render_builder_mode` импортируется — то есть модуль `app.py`
синтаксически валиден и подтягивает builder/templates корректно.
"""

from __future__ import annotations

import pytest


def test_builder_mode_imports() -> None:
    """``from gostforge.web.app import _render_builder_mode`` работает."""
    pytest.importorskip("streamlit")
    from gostforge.web.app import _render_builder_mode

    assert callable(_render_builder_mode)


def test_build_template_docx_bytes_returns_bytes() -> None:
    """Хелпер сборки болванки возвращает непустые байты .docx.

    Это базовая проверка интеграции: builder.templates → builder.save →
    bytes. Streamlit здесь не задействован.
    """
    pytest.importorskip("streamlit")
    from gostforge.web.app import _build_template_docx_bytes

    data = _build_template_docx_bytes(
        "coursework",
        title="Тестовая курсовая",
        author="Иванов И. И.",
        supervisor="",
        organization="",
        year=2026,
    )
    # docx — это zip-архив, начинается с сигнатуры PK\x03\x04.
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"


def test_build_template_docx_bytes_research_report() -> None:
    """research_report_template — обезличенный, author игнорируется."""
    pytest.importorskip("streamlit")
    from gostforge.web.app import _build_template_docx_bytes

    data = _build_template_docx_bytes(
        "research_report",
        title="Отчёт о НИР",
        author="(не используется)",
        supervisor="(не используется)",
        organization="ООО Ромашка",
        year=2026,
    )
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"
