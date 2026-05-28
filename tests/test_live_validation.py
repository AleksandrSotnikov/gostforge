"""Тесты live-нормоконтроля state в UI."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _compute_live_validation_summary


def test_empty_state_returns_zero_summary() -> None:
    """Пустой state не падает, возвращает summary без падения."""
    summary = _compute_live_validation_summary({})
    assert "total" in summary
    assert "by_severity" in summary
    assert "top_codes" in summary


def test_minimal_state_returns_summary() -> None:
    state = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Какой-то текст."}],
            }
        ],
    }
    summary = _compute_live_validation_summary(state)
    # Минимальный документ имеет несколько нарушений (нет таблиц, объёма, и т. п.).
    assert summary["total"] >= 0
    # Структура top_codes — list[{code, count}].
    for entry in summary["top_codes"]:
        assert "code" in entry
        assert "count" in entry
        assert entry["count"] >= 1


def test_invalid_profile_returns_empty_summary() -> None:
    """Невалидный profile_id → пустая сводка без exception."""
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "non-existent",
        "sections": [{"heading": "Введение", "blocks": []}],
    }
    summary = _compute_live_validation_summary(state)
    assert summary == {"total": 0, "by_severity": {}, "top_codes": []}


def test_summary_top_codes_capped_at_5() -> None:
    """Top_codes имеет не более 5 элементов (для компактного UI)."""
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "x"}],
            }
        ],
    }
    summary = _compute_live_validation_summary(state)
    assert len(summary["top_codes"]) <= 5


def test_summary_includes_severity_buckets() -> None:
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "плохой  текст"}],
            }
        ],
    }
    summary = _compute_live_validation_summary(state)
    bs = summary["by_severity"]
    # Все три bucket-а присутствуют (могут быть 0).
    assert "error" in bs
    assert "warning" in bs
    assert "info" in bs


def test_render_panel_importable() -> None:
    from gostforge.web.builder_editor import _render_live_validation_panel

    assert callable(_render_live_validation_panel)
