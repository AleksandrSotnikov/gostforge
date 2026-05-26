"""Smoke-тест UI-функции PDF-превью в конструкторе.

Реальную конвертацию через LibreOffice не запускаем (зависимость
снаружи), проверяем что _render_pdf_preview корректно обрабатывает
отсутствие LibreOffice (показывает error, не падает) и что функция
импортируется.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("streamlit")

import streamlit as st


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def test_render_pdf_preview_importable() -> None:
    from gostforge.web.builder_editor import _render_pdf_preview

    assert callable(_render_pdf_preview)


def test_render_pdf_preview_handles_missing_libreoffice() -> None:
    """Если LibreOffice не найден — функция не падает."""
    from gostforge.pdf_exporter import LibreOfficeNotFoundError
    from gostforge.web.builder_editor import _render_pdf_preview

    with patch(
        "gostforge.pdf_exporter.convert_to_pdf",
        side_effect=LibreOfficeNotFoundError("not found"),
    ):
        # Не должно бросить.
        _render_pdf_preview(b"fake docx bytes")


def test_render_pdf_preview_handles_subprocess_error() -> None:
    """Произвольная ошибка LibreOffice — показывает error, не падает."""
    from gostforge.web.builder_editor import _render_pdf_preview

    with patch(
        "gostforge.pdf_exporter.convert_to_pdf",
        side_effect=RuntimeError("конвертация подвисла"),
    ):
        _render_pdf_preview(b"fake docx bytes")
