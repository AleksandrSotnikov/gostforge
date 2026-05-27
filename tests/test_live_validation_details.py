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
    for item in items:
        assert isinstance(item, dict)
        assert set(item.keys()) == {"code", "severity", "message", "suggestion"}
        for value in item.values():
            assert isinstance(value, str)
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
    for item in items:
        assert set(item.keys()) == {"code", "severity", "message", "suggestion"}
        assert item["severity"] in {"error", "warning", "info"}
