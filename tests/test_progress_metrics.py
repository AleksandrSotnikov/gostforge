# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты _compute_progress_metrics — счётчики прогресса работы."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _compute_progress_metrics


def test_empty_state() -> None:
    metrics = _compute_progress_metrics({"sections": []})
    assert metrics["sections_total"] == 0
    assert metrics["sections_filled"] == 0
    assert metrics["paragraphs_total"] == 0
    assert metrics["total_words"] == 0


def test_single_filled_section() -> None:
    state = {
        "sections": [
            {
                "heading": "X",
                "blocks": [
                    {"kind": "paragraph", "text": "Это полный параграф работы."}
                ],
            }
        ]
    }
    m = _compute_progress_metrics(state)
    assert m["sections_total"] == 1
    assert m["sections_filled"] == 1
    assert m["paragraphs_total"] == 1
    assert m["paragraphs_nonempty"] == 1
    # «Это полный параграф работы.» — 4 слова.
    assert m["total_words"] == 4


def test_empty_section_not_counted_as_filled() -> None:
    state = {
        "sections": [
            {"heading": "X", "blocks": []},
            {"heading": "Y", "blocks": [{"kind": "paragraph", "text": ""}]},
        ]
    }
    m = _compute_progress_metrics(state)
    assert m["sections_total"] == 2
    assert m["sections_filled"] == 0
    assert m["paragraphs_total"] == 1
    assert m["paragraphs_nonempty"] == 0


def test_counts_tables_figures_formulas_lists() -> None:
    state = {
        "sections": [
            {
                "heading": "X",
                "blocks": [
                    {"kind": "table", "headers": [], "rows": []},
                    {"kind": "table", "headers": [], "rows": []},
                    {"kind": "figure", "image_path": "a.png"},
                    {"kind": "formula", "latex": "x"},
                    {
                        "kind": "list",
                        "ordered": False,
                        "items": ["a", "b", "c"],
                    },
                ],
            }
        ]
    }
    m = _compute_progress_metrics(state)
    assert m["tables"] == 2
    assert m["figures"] == 1
    assert m["formulas"] == 1
    assert m["list_items"] == 3


def test_bibliography_counted() -> None:
    state = {
        "sections": [
            {
                "heading": "Список",
                "is_bibliography": True,
                "references": ["A", "B", "C"],
            }
        ]
    }
    m = _compute_progress_metrics(state)
    assert m["references_total"] == 3
    assert m["sections_filled"] == 1


def test_subsection_contributes_to_section_filled() -> None:
    """Раздел считается заполненным если хоть один подраздел имеет контент."""
    state = {
        "sections": [
            {
                "heading": "Глава 1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "1.1",
                        "blocks": [{"kind": "paragraph", "text": "текст"}],
                    }
                ],
            }
        ]
    }
    m = _compute_progress_metrics(state)
    assert m["sections_filled"] == 1
    assert m["paragraphs_nonempty"] == 1


def test_runs_paragraph_counts_words() -> None:
    """Параграф в rich-формате (runs) тоже считается."""
    state = {
        "sections": [
            {
                "heading": "X",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "runs": [
                            {"kind": "text", "text": "Один два "},
                            {"kind": "text", "text": "три"},
                        ],
                    }
                ],
            }
        ]
    }
    m = _compute_progress_metrics(state)
    assert m["paragraphs_nonempty"] == 1
    assert m["total_words"] == 3


def test_deep_subsubsection_counted() -> None:
    """Sub-subsection (level=3) тоже учитывается."""
    state = {
        "sections": [
            {
                "heading": "X",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "X.1",
                        "blocks": [],
                        "subsections": [
                            {
                                "heading": "X.1.1",
                                "blocks": [
                                    {"kind": "paragraph", "text": "глубокий текст"}
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    m = _compute_progress_metrics(state)
    assert m["sections_filled"] == 1
    assert m["paragraphs_nonempty"] == 1
    assert m["total_words"] == 2
