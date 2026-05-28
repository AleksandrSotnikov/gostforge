"""Тесты подсветки поиска и авто-нумерации заголовков."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import (
    _bulk_auto_number_headings,
    _highlight_query_in_text,
    _is_structural_heading,
    _strip_existing_number,
)

# --- _highlight_query_in_text ---


def test_highlight_basic() -> None:
    out = _highlight_query_in_text("Алгоритм Дейкстры", "дейкстры")
    assert "<mark>" in out
    assert "</mark>" in out
    # Регистр сохраняется (Дейкстры, не дейкстры).
    assert "<mark>Дейкстры</mark>" in out


def test_highlight_no_match() -> None:
    out = _highlight_query_in_text("Алгоритм X", "флойд")
    assert "<mark>" not in out
    assert out == "Алгоритм X"


def test_highlight_escapes_html() -> None:
    """HTML-инъекции в тексте экранируются."""
    out = _highlight_query_in_text("<script>x</script> привет", "x")
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


def test_highlight_query_with_special_regex_chars() -> None:
    """Спец-символы в query не ломают regex."""
    out = _highlight_query_in_text("Текст 1.1.1 подраздел", "1.1")
    assert "<mark>" in out


def test_highlight_empty_query_returns_text() -> None:
    assert _highlight_query_in_text("Hello", "") == "Hello"


# --- _is_structural_heading ---


@pytest.mark.parametrize(
    "heading",
    [
        "Введение",
        "введение",
        "ВВЕДЕНИЕ",
        "Заключение",
        "Содержание",
        "Реферат",
        "Список использованных источников",
        "1. Введение",  # с существующей нумерацией
        "1 введение",
        "Приложение А",
        "Приложение Б",
    ],
)
def test_structural_heading_detection(heading: str) -> None:
    assert _is_structural_heading(heading)


@pytest.mark.parametrize(
    "heading",
    [
        "Глава 1",
        "Основная часть",
        "Анализ предметной области",
        "1. Постановка задачи",  # это глава с номером
    ],
)
def test_non_structural_heading(heading: str) -> None:
    # "1. Постановка задачи" — это содержательная глава (не структурная).
    # _is_structural_heading должен вернуть False.
    assert not _is_structural_heading(heading)


# --- _strip_existing_number ---


def test_strip_simple_number() -> None:
    assert _strip_existing_number("1 Глава") == "Глава"
    assert _strip_existing_number("1. Глава") == "Глава"


def test_strip_multilevel_number() -> None:
    assert _strip_existing_number("1.1 Подраздел") == "Подраздел"
    assert _strip_existing_number("1.1. Подраздел") == "Подраздел"
    assert _strip_existing_number("1.1.1 Пункт") == "Пункт"


def test_strip_no_number() -> None:
    assert _strip_existing_number("Введение") == "Введение"


# --- _bulk_auto_number_headings ---


def test_autonumber_only_chapters() -> None:
    state = {
        "sections": [
            {"heading": "Введение", "blocks": []},
            {"heading": "Анализ", "blocks": []},
            {"heading": "Проектирование", "blocks": []},
            {"heading": "Заключение", "blocks": []},
        ]
    }
    numbered = _bulk_auto_number_headings(state)
    assert numbered == 2  # «Анализ» и «Проектирование»
    headings = [s["heading"] for s in state["sections"]]
    assert headings == ["Введение", "1 Анализ", "2 Проектирование", "Заключение"]


def test_autonumber_with_subsections() -> None:
    state = {
        "sections": [
            {
                "heading": "Анализ",
                "blocks": [],
                "subsections": [
                    {"heading": "Постановка задачи", "blocks": []},
                    {"heading": "Существующие решения", "blocks": []},
                ],
            }
        ]
    }
    _bulk_auto_number_headings(state)
    chapter = state["sections"][0]
    assert chapter["heading"] == "1 Анализ"
    assert chapter["subsections"][0]["heading"] == "1.1 Постановка задачи"
    assert chapter["subsections"][1]["heading"] == "1.2 Существующие решения"


def test_autonumber_with_subsubsections() -> None:
    state = {
        "sections": [
            {
                "heading": "Анализ",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "Подраздел",
                        "blocks": [],
                        "subsections": [
                            {"heading": "Пункт А", "blocks": []},
                            {"heading": "Пункт Б", "blocks": []},
                        ],
                    }
                ],
            }
        ]
    }
    _bulk_auto_number_headings(state)
    sub = state["sections"][0]["subsections"][0]
    assert sub["heading"] == "1.1 Подраздел"
    assert sub["subsections"][0]["heading"] == "1.1.1 Пункт А"
    assert sub["subsections"][1]["heading"] == "1.1.2 Пункт Б"


def test_autonumber_replaces_existing_numbers() -> None:
    """Повторный вызов не накапливает «1 1 1 Глава»."""
    state = {
        "sections": [
            {"heading": "1 Глава", "blocks": []},
        ]
    }
    _bulk_auto_number_headings(state)
    assert state["sections"][0]["heading"] == "1 Глава"
    # Повторно — всё ещё «1 Глава», без удваивания.
    _bulk_auto_number_headings(state)
    assert state["sections"][0]["heading"] == "1 Глава"


def test_autonumber_normalizes_structural_headings() -> None:
    """Случайная нумерация на структурном разделе снимается."""
    state = {
        "sections": [
            {"heading": "1. Введение", "blocks": []},
            {"heading": "Глава 1", "blocks": []},
        ]
    }
    _bulk_auto_number_headings(state)
    # Введение всё ещё структурное — нумерация снята.
    assert state["sections"][0]["heading"] == "Введение"
    assert state["sections"][1]["heading"] == "1 Глава 1"


def test_autonumber_appendix_not_numbered() -> None:
    state = {
        "sections": [
            {"heading": "Анализ", "blocks": []},
            {"heading": "Приложение А", "blocks": []},
            {"heading": "Приложение Б", "blocks": []},
        ]
    }
    _bulk_auto_number_headings(state)
    assert state["sections"][0]["heading"] == "1 Анализ"
    # Приложения сохраняют буквенную нумерацию.
    assert state["sections"][1]["heading"] == "Приложение А"
    assert state["sections"][2]["heading"] == "Приложение Б"
