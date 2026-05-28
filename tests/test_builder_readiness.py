"""Тесты чистого helper-а _compute_readiness конструктора работ.

Проверяют только логику обнаружения структурных элементов ГОСТ по
заголовкам разделов 1-го уровня. Streamlit-рендер не поднимается.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _compute_readiness


def test_full_state_all_elements_present() -> None:
    """Полный state со всеми элементами → все 7 флагов True."""
    state: dict[str, Any] = {
        "sections": [
            {"heading": "Титульный лист"},
            {"heading": "Содержание"},
            {"heading": "Введение"},
            {"heading": "1 Анализ"},
            {"heading": "Заключение"},
            {"heading": "Список использованных источников", "is_bibliography": True},
            {"heading": "Приложение А"},
        ],
    }
    flags = _compute_readiness(state)
    assert all(flags.values())
    assert set(flags) == {
        "Титульный лист",
        "Содержание",
        "Введение",
        "Основная часть",
        "Заключение",
        "Список источников",
        "Приложения",
    }


def test_partial_state_only_intro_and_chapter() -> None:
    """Только «Введение» и «1 Анализ» → True у них, остальное False."""
    state: dict[str, Any] = {
        "sections": [
            {"heading": "Введение"},
            {"heading": "1 Анализ"},
        ],
    }
    flags = _compute_readiness(state)
    assert flags["Введение"] is True
    assert flags["Основная часть"] is True
    assert flags["Титульный лист"] is False
    assert flags["Содержание"] is False
    assert flags["Заключение"] is False
    assert flags["Список источников"] is False
    assert flags["Приложения"] is False


def test_bibliography_flag_marks_sources() -> None:
    """Раздел с is_bibliography=True → «Список источников» True."""
    state: dict[str, Any] = {
        "sections": [
            {"heading": "Список", "is_bibliography": True},
        ],
    }
    flags = _compute_readiness(state)
    assert flags["Список источников"] is True


def test_appendix_heading_marks_appendices() -> None:
    """Раздел «Приложение А» → «Приложения» True."""
    state: dict[str, Any] = {
        "sections": [
            {"heading": "Приложение А"},
        ],
    }
    flags = _compute_readiness(state)
    assert flags["Приложения"] is True
