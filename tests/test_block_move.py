"""Тесты перемещения блоков в редакторе раздела конструктора."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _move_block


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
