"""Тесты детального live-нормоконтроля конструктора (builder_editor)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _live_validation_items


def test_live_validation_items_returns_detailed_dicts() -> None:
    """State с заведомым нарушением → список dict с нужными ключами."""
    state: dict[str, Any] = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Моя глава",
                "blocks": [{"kind": "paragraph", "text": "текст"}],
            }
        ],
    }
    items = _live_validation_items(state)
    assert isinstance(items, list)
    expected_keys = {"code", "severity", "message", "suggestion"}
    for item in items:
        assert isinstance(item, dict)
        # Минимум — поля для отображения. Доп. поля (location, section_idx)
        # — для навигации.
        assert expected_keys.issubset(item.keys())
        for key in expected_keys:
            assert isinstance(item[key], str)
        assert item["severity"] in {"error", "warning", "info"}


def test_live_validation_items_empty_state_does_not_crash() -> None:
    """Пустой state (без разделов) не должен ронять helper.

    Документ из пустого state всё равно собирается (без разделов),
    поэтому structural-проверки могут вернуть нарушения. Главное —
    функция отрабатывает без исключения и возвращает корректный
    список dict с нужными ключами.
    """
    state: dict[str, Any] = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [],
    }
    items = _live_validation_items(state)
    assert isinstance(items, list)
    expected_keys = {"code", "severity", "message", "suggestion"}
    for item in items:
        assert expected_keys.issubset(item.keys())
        assert item["severity"] in {"error", "warning", "info"}


def test_live_validation_items_include_section_idx_for_navigation() -> None:
    """Каждый item имеет `section_idx` (int) — индекс top-level раздела
    для кнопки «→ К разделу»; -1 если location не привязан к разделу."""
    state: dict[str, Any] = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {"heading": "Глава 1", "blocks": [{"kind": "paragraph", "text": "x"}]},
            {"heading": "Глава 2", "blocks": [{"kind": "paragraph", "text": "y"}]},
        ],
    }
    items = _live_validation_items(state)
    for item in items:
        assert "section_idx" in item
        assert isinstance(item["section_idx"], int)
        # -1 (не привязан) или 0..N-1.
        assert item["section_idx"] >= -1
        assert item["section_idx"] < len(state["sections"])
