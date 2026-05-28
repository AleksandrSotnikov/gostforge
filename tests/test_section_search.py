"""Тесты функции поиска по разделам в UI."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _section_matches_query


def test_empty_query_matches() -> None:
    """Пустой query → всегда True (фильтр выключен)."""
    sec = {"heading": "X", "blocks": []}
    assert _section_matches_query(sec, "")


def test_query_matches_heading() -> None:
    sec = {"heading": "Введение в анализ", "blocks": []}
    assert _section_matches_query(sec, "введ")
    assert _section_matches_query(sec, "анализ")
    assert not _section_matches_query(sec, "заключение")


def test_query_matches_paragraph_text() -> None:
    sec = {
        "heading": "Глава 1",
        "blocks": [{"kind": "paragraph", "text": "Алгоритм Дейкстры используется"}],
    }
    assert _section_matches_query(sec, "дейкстры")
    assert not _section_matches_query(sec, "флойда")


def test_query_matches_paragraph_runs() -> None:
    """Параграф в rich-формате (runs) — текст runs тоже ищется."""
    sec = {
        "heading": "Глава 1",
        "blocks": [
            {
                "kind": "paragraph",
                "runs": [
                    {"kind": "text", "text": "Сначала "},
                    {"kind": "text", "text": "алгоритм Дейкстры"},
                ],
            }
        ],
    }
    assert _section_matches_query(sec, "дейкстры")


def test_query_matches_table() -> None:
    sec = {
        "heading": "Х",
        "blocks": [
            {
                "kind": "table",
                "headers": ["Параметр", "Значение"],
                "rows": [["шрифт", "Times New Roman"]],
                "caption": "Параметры оформления",
            }
        ],
    }
    assert _section_matches_query(sec, "оформления")  # caption
    assert _section_matches_query(sec, "times new")  # row
    assert _section_matches_query(sec, "параметр")  # header


def test_query_matches_figure_caption() -> None:
    sec = {
        "heading": "X",
        "blocks": [
            {
                "kind": "figure",
                "image_path": "fig.png",
                "caption": "Схема архитектуры",
            }
        ],
    }
    assert _section_matches_query(sec, "архитектуры")


def test_query_matches_list_item() -> None:
    sec = {
        "heading": "X",
        "blocks": [
            {
                "kind": "list",
                "ordered": False,
                "items": ["проанализировать", "реализовать"],
            }
        ],
    }
    assert _section_matches_query(sec, "реализовать")


def test_query_matches_reference() -> None:
    sec = {
        "heading": "Список",
        "is_bibliography": True,
        "references": ["Кнут Д. Э. Искусство программирования. — М., 2007."],
    }
    assert _section_matches_query(sec, "кнут")


def test_query_matches_subsection_heading() -> None:
    sec = {
        "heading": "Глава 1",
        "blocks": [],
        "subsections": [
            {"heading": "1.1 Постановка задачи", "blocks": []},
            {"heading": "1.2 Анализ литературы", "blocks": []},
        ],
    }
    assert _section_matches_query(sec, "литературы")
    assert _section_matches_query(sec, "постановка")


def test_query_matches_deep_subsubsection() -> None:
    """Поиск ищет на любой глубине вложенности (3+)."""
    sec = {
        "heading": "Глава 1",
        "blocks": [],
        "subsections": [
            {
                "heading": "1.1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "1.1.1 Конкретный пункт",
                        "blocks": [{"kind": "paragraph", "text": "deep text"}],
                    }
                ],
            }
        ],
    }
    assert _section_matches_query(sec, "конкретный")
    assert _section_matches_query(sec, "deep")


def test_query_case_insensitive() -> None:
    sec = {"heading": "ВВЕДЕНИЕ", "blocks": []}
    # Запрос lowercase, заголовок UPPERCASE — должно совпадать.
    assert _section_matches_query(sec, "введ")


def test_query_no_match_returns_false() -> None:
    sec = {
        "heading": "Glава X",
        "blocks": [{"kind": "paragraph", "text": "обычный текст"}],
    }
    assert not _section_matches_query(sec, "несуществующий")
