# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты глубокой структуры разделов и переупорядочивания."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import streamlit as st

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.model import LogicalSection
from gostforge.parser import parse_docx
from gostforge.profile import load_profile
from gostforge.web.builder_editor import (
    _build_document_from_state,
    _move_section_to,
    document_to_state,
)


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state["builder_state"] = {
        "sections": [],
        "active_section_index": 0,
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
    }


# --- _move_section_to ---


def test_move_section_forward() -> None:
    state = st.session_state["builder_state"]
    state["sections"] = [
        {"heading": "A", "blocks": []},
        {"heading": "B", "blocks": []},
        {"heading": "C", "blocks": []},
    ]
    _move_section_to(0, 2)  # A → конец
    assert [s["heading"] for s in state["sections"]] == ["B", "C", "A"]


def test_move_section_backward() -> None:
    state = st.session_state["builder_state"]
    state["sections"] = [
        {"heading": "A", "blocks": []},
        {"heading": "B", "blocks": []},
        {"heading": "C", "blocks": []},
    ]
    _move_section_to(2, 0)  # C → начало
    assert [s["heading"] for s in state["sections"]] == ["C", "A", "B"]


def test_move_section_to_same_position_no_op() -> None:
    state = st.session_state["builder_state"]
    state["sections"] = [
        {"heading": "A", "blocks": []},
        {"heading": "B", "blocks": []},
    ]
    _move_section_to(0, 0)
    assert [s["heading"] for s in state["sections"]] == ["A", "B"]


def test_move_section_out_of_range_no_op() -> None:
    state = st.session_state["builder_state"]
    state["sections"] = [{"heading": "A", "blocks": []}]
    _move_section_to(99, 0)  # source out of range
    assert [s["heading"] for s in state["sections"]] == ["A"]


def test_move_section_clamps_target_to_valid_range() -> None:
    state = st.session_state["builder_state"]
    state["sections"] = [
        {"heading": "A", "blocks": []},
        {"heading": "B", "blocks": []},
    ]
    _move_section_to(0, 100)  # target слишком большой → конец
    assert [s["heading"] for s in state["sections"]] == ["B", "A"]


def test_move_section_updates_active_index_when_moving_active() -> None:
    state = st.session_state["builder_state"]
    state["sections"] = [
        {"heading": "A", "blocks": []},
        {"heading": "B", "blocks": []},
        {"heading": "C", "blocks": []},
    ]
    state["active_section_index"] = 0
    _move_section_to(0, 2)
    # Активным остаётся переместившийся раздел.
    assert state["active_section_index"] == 2


def test_move_section_updates_active_when_shifted() -> None:
    state = st.session_state["builder_state"]
    state["sections"] = [
        {"heading": "A", "blocks": []},
        {"heading": "B", "blocks": []},
        {"heading": "C", "blocks": []},
    ]
    state["active_section_index"] = 1  # B активный
    _move_section_to(0, 2)  # A в конец → B сдвинулся вверх на индекс 0
    assert state["sections"][0]["heading"] == "B"
    assert state["active_section_index"] == 0


# --- Sub-subsections (level 3) ---


def test_state_with_subsubsection_builds_correctly(tmp_path: Path) -> None:
    """state с subsection.subsections даёт level=3 в Document."""
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Глава 1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "1.1 Подраздел",
                        "blocks": [],
                        "subsections": [
                            {
                                "heading": "1.1.1 Пункт",
                                "blocks": [
                                    {"kind": "paragraph", "text": "Текст пункта."}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    data = _build_document_from_state(state)
    out = tmp_path / "deep.docx"
    out.write_bytes(data)
    doc = parse_docx(out)
    # Найдём в структуре LogicalSection level=3.
    found_l3 = []

    def walk(items: list) -> None:  # type: ignore[no-untyped-def]
        for item in items:
            if isinstance(item, LogicalSection):
                if item.level == 3:
                    found_l3.append(item)
                walk(item.children)

    walk(doc.page_sections[0].content)
    assert found_l3, (
        f"Не найден LogicalSection level=3. "
        f"Заголовки в документе: "
        f"{[h for h in [t.text for ps in doc.page_sections for c in ps.content if isinstance(c, LogicalSection) for t in c.heading]]}"
    )


def test_subsubsection_round_trip(tmp_path: Path) -> None:
    """state → docx → state — пункт 3-го уровня сохраняется."""
    state_in = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Глава 1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "1.1 Подраздел",
                        "blocks": [],
                        "subsections": [
                            {
                                "heading": "1.1.1 Пункт",
                                "blocks": [
                                    {"kind": "paragraph", "text": "Текст."}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    data = _build_document_from_state(state_in)
    out = tmp_path / "rt.docx"
    out.write_bytes(data)
    doc = parse_docx(out)
    state_out = document_to_state(doc)
    chapter = state_out["sections"][0]
    sub = chapter.get("subsections", [])
    assert sub, "Subsection не найден"
    subsub = sub[0].get("subsections", [])
    assert subsub, "Sub-subsection (level=3) не найден"
    assert "пункт" in subsub[0]["heading"].lower()


def test_builder_subsection_recursion_creates_level_3() -> None:
    """SectionBuilder.subsection() рекурсивно — level повышается на 1."""
    b = work("X", year=2026)
    sec = b.section("Глава 1")
    sub = sec.subsection("1.1 Подраздел")
    subsub = sub.subsection("1.1.1 Пункт")
    subsub.paragraph("Текст.")
    doc = b.build()
    # Найдём LogicalSection с level=3.
    found = []

    def walk(items: list) -> None:  # type: ignore[no-untyped-def]
        for item in items:
            if isinstance(item, LogicalSection):
                if item.level >= 3:
                    found.append(item)
                walk(item.children)

    walk(doc.page_sections[0].content)
    assert found, "Builder не создал level=3"


def test_render_subsubsections_editor_importable() -> None:
    """UI-функция импортируется (smoke)."""
    from gostforge.web.builder_editor import _render_subsubsections_editor

    assert callable(_render_subsubsections_editor)
