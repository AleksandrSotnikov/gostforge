# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты undo/redo для visual-builder state (шаг 7 Фазы 2.5).

streamlit.session_state — это объектно-словарный синглтон, который не
переинициализируется между вызовами. Тут он используется как dict; на
старте каждого теста очищаем известные ключи.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("streamlit")

import streamlit as st

from gostforge.web.builder_editor import (
    _auto_snapshot_if_changed,
    _can_redo,
    _can_undo,
    _push_history_snapshot,
    _redo_state,
    _undo_state,
)


_RESET_KEYS = ("builder_state", "builder_history", "builder_history_cursor")


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    """Очистка session_state перед каждым тестом."""
    for key in _RESET_KEYS:
        if key in st.session_state:
            del st.session_state[key]


def _set_state(payload: dict[str, Any]) -> None:
    st.session_state["builder_state"] = payload


def test_first_snapshot_creates_history_entry() -> None:
    _set_state({"title": "A"})
    _push_history_snapshot()
    assert len(st.session_state["builder_history"]) == 1
    assert st.session_state["builder_history_cursor"] == 0


def test_two_snapshots_advance_cursor() -> None:
    _set_state({"title": "A"})
    _push_history_snapshot()
    _set_state({"title": "B"})
    _push_history_snapshot()
    assert st.session_state["builder_history_cursor"] == 1
    assert st.session_state["builder_history"][0] == {"title": "A"}
    assert st.session_state["builder_history"][1] == {"title": "B"}


def test_undo_restores_previous_snapshot() -> None:
    _set_state({"title": "A"})
    _push_history_snapshot()
    _set_state({"title": "B"})
    _push_history_snapshot()
    ok = _undo_state()
    assert ok is True
    assert st.session_state["builder_state"] == {"title": "A"}
    assert st.session_state["builder_history_cursor"] == 0


def test_undo_at_start_returns_false() -> None:
    _set_state({"title": "A"})
    _push_history_snapshot()
    assert _undo_state() is False
    assert st.session_state["builder_state"] == {"title": "A"}


def test_redo_after_undo_restores_forward_snapshot() -> None:
    _set_state({"title": "A"})
    _push_history_snapshot()
    _set_state({"title": "B"})
    _push_history_snapshot()
    _undo_state()
    assert st.session_state["builder_state"] == {"title": "A"}
    ok = _redo_state()
    assert ok is True
    assert st.session_state["builder_state"] == {"title": "B"}


def test_redo_at_end_returns_false() -> None:
    _set_state({"title": "A"})
    _push_history_snapshot()
    assert _redo_state() is False


def test_can_undo_and_can_redo_reflect_position() -> None:
    _set_state({"title": "A"})
    _push_history_snapshot()
    _set_state({"title": "B"})
    _push_history_snapshot()
    assert _can_undo() is True
    assert _can_redo() is False
    _undo_state()
    assert _can_undo() is False
    assert _can_redo() is True


def test_new_snapshot_after_undo_truncates_future() -> None:
    """Класический branch-and-truncate: после undo новая мутация убивает redo-будущее."""
    _set_state({"title": "A"})
    _push_history_snapshot()
    _set_state({"title": "B"})
    _push_history_snapshot()
    _set_state({"title": "C"})
    _push_history_snapshot()
    # cursor=2 [A, B, C]
    _undo_state()  # cursor=1, state=B
    _undo_state()  # cursor=0, state=A
    # Новая ветка: state становится «X», snapshot уничтожает B, C.
    _set_state({"title": "X"})
    _push_history_snapshot()
    assert [s["title"] for s in st.session_state["builder_history"]] == ["A", "X"]
    assert st.session_state["builder_history_cursor"] == 1
    assert _can_redo() is False


def test_history_buffer_limited_to_50_snapshots() -> None:
    """Кольцевой буфер: при превышении лимита старейший snapshot выпадает."""
    for i in range(60):
        _set_state({"step": i})
        _push_history_snapshot()
    assert len(st.session_state["builder_history"]) == 50
    # cursor — на последнем элементе.
    assert st.session_state["builder_history_cursor"] == 49
    # Самый старый snapshot — это шаг 10 (60-50=10).
    assert st.session_state["builder_history"][0] == {"step": 10}
    assert st.session_state["builder_history"][-1] == {"step": 59}


def test_auto_snapshot_no_op_when_state_matches_cursor() -> None:
    """Повторный rerun без мутаций не должен плодить snapshot-ы."""
    _set_state({"title": "A"})
    _auto_snapshot_if_changed()  # первый — добавит
    _auto_snapshot_if_changed()  # повтор — нет изменений
    _auto_snapshot_if_changed()
    assert len(st.session_state["builder_history"]) == 1


def test_auto_snapshot_pushes_when_state_changes() -> None:
    _set_state({"title": "A"})
    _auto_snapshot_if_changed()
    _set_state({"title": "B"})
    _auto_snapshot_if_changed()
    assert len(st.session_state["builder_history"]) == 2
    assert st.session_state["builder_history"][-1] == {"title": "B"}


def test_auto_snapshot_after_undo_does_not_create_extra_entry() -> None:
    """После undo state == history[cursor] — auto-snapshot не должен срабатывать."""
    _set_state({"title": "A"})
    _push_history_snapshot()
    _set_state({"title": "B"})
    _push_history_snapshot()
    _undo_state()
    assert st.session_state["builder_history_cursor"] == 0
    _auto_snapshot_if_changed()  # после undo не должен push'ить
    assert len(st.session_state["builder_history"]) == 2
    assert st.session_state["builder_history_cursor"] == 0


def test_snapshot_deepcopies_state_not_aliases() -> None:
    """Изменение state после snapshot не должно затрагивать сохранённую копию."""
    payload: dict[str, Any] = {"title": "A", "sections": [{"id": "s1"}]}
    _set_state(payload)
    _push_history_snapshot()
    payload["sections"][0]["id"] = "MUTATED"
    assert st.session_state["builder_history"][0]["sections"][0]["id"] == "s1"
