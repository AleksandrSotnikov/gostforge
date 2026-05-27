"""Тесты перемещения и дублирования блоков в редакторе раздела."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import (
    _duplicate_block,
    _move_block,
    _move_block_to_section,
)


def _state() -> dict[str, object]:
    return {
        "sections": [
            {"heading": "A", "blocks": [{"kind": "x"}, {"kind": "y"}]},
            {"heading": "B", "blocks": [{"kind": "z"}]},
        ]
    }


def test_move_block_to_section_appends_to_target() -> None:
    state = _state()
    assert _move_block_to_section(state, 0, 0, 1) is True
    secs = state["sections"]
    assert [b["kind"] for b in secs[0]["blocks"]] == ["y"]
    assert [b["kind"] for b in secs[1]["blocks"]] == ["z", "x"]


def test_move_block_to_section_same_section_noop() -> None:
    state = _state()
    assert _move_block_to_section(state, 0, 0, 0) is False
    assert [b["kind"] for b in state["sections"][0]["blocks"]] == ["x", "y"]


def test_move_block_to_section_bad_indices() -> None:
    state = _state()
    assert _move_block_to_section(state, 0, 9, 1) is False  # block_idx вне диапазона
    assert _move_block_to_section(state, 5, 0, 1) is False  # from вне диапазона
    assert _move_block_to_section(state, 0, 0, 9) is False  # to вне диапазона


def test_move_block_to_section_target_without_blocks_key() -> None:
    state = {"sections": [{"heading": "A", "blocks": [{"kind": "x"}]}, {"heading": "B"}]}
    assert _move_block_to_section(state, 0, 0, 1) is True
    assert state["sections"][1]["blocks"] == [{"kind": "x"}]


def _blocks() -> list[dict[str, str]]:
    return [{"kind": "a"}, {"kind": "b"}, {"kind": "c"}]


def test_move_block_up() -> None:
    blocks = _blocks()
    _move_block(blocks, 2, 1)
    assert [b["kind"] for b in blocks] == ["a", "c", "b"]


def test_move_block_down() -> None:
    blocks = _blocks()
    _move_block(blocks, 0, 1)
    assert [b["kind"] for b in blocks] == ["b", "a", "c"]


def test_move_block_clamps_to_edges() -> None:
    blocks = _blocks()
    _move_block(blocks, 0, -1)  # вверх с первой позиции — клампится в 0 = no-op
    assert [b["kind"] for b in blocks] == ["a", "b", "c"]
    _move_block(blocks, 2, 5)  # вниз с последней — клампится в конец = no-op
    assert [b["kind"] for b in blocks] == ["a", "b", "c"]


def test_move_block_same_position_noop() -> None:
    blocks = _blocks()
    _move_block(blocks, 1, 1)
    assert [b["kind"] for b in blocks] == ["a", "b", "c"]


def test_move_block_out_of_range_and_empty() -> None:
    blocks = _blocks()
    _move_block(blocks, 9, 0)  # from вне диапазона — no-op
    assert [b["kind"] for b in blocks] == ["a", "b", "c"]
    empty: list[dict[str, str]] = []
    _move_block(empty, 0, 1)  # пустой список — no-op
    assert empty == []


def test_duplicate_block_inserts_after() -> None:
    blocks = _blocks()
    _duplicate_block(blocks, 0)
    assert [b["kind"] for b in blocks] == ["a", "a", "b", "c"]


def test_duplicate_block_is_deep_copy() -> None:
    blocks: list[dict[str, object]] = [{"kind": "list", "items": ["x"]}]
    _duplicate_block(blocks, 0)
    # Правка копии не затрагивает оригинал.
    clone = blocks[1]
    assert isinstance(clone["items"], list)
    clone["items"].append("y")
    assert blocks[0]["items"] == ["x"]


def test_duplicate_block_out_of_range_noop() -> None:
    blocks = _blocks()
    _duplicate_block(blocks, 9)
    assert [b["kind"] for b in blocks] == ["a", "b", "c"]
