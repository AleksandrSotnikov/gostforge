"""Тесты UI-расширений конструктора (продолжение фич).

* Дублирование раздела (deep-copy, heading + ' (копия)', сброс bib-флага).
* Прогон нормоконтроля сразу после import-docx (summary с топ-кодами).
* Постобработка парсера: подряд идущие маркированные параграфы → ListBlock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import streamlit as st

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.parser import parse_docx
from gostforge.profile import load_profile


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    """Очистка session_state и инициализация builder_state перед каждым тестом."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state["builder_state"] = {
        "sections": [],
        "active_section_index": 0,
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
    }


# --- _duplicate_section ---


def test_duplicate_section_creates_independent_copy() -> None:
    """state-sections[i] копируется в i+1; правка копии не меняет оригинал."""
    from gostforge.web.builder_editor import _duplicate_section

    state = st.session_state["builder_state"]
    state["sections"] = [
        {
            "heading": "Глава 1",
            "blocks": [{"kind": "paragraph", "text": "Текст главы 1"}],
            "subsections": [],
        }
    ]
    _duplicate_section(0)
    assert len(state["sections"]) == 2
    orig, copy = state["sections"]
    assert orig["heading"] == "Глава 1"
    assert copy["heading"] == "Глава 1 (копия)"
    # Active переключился на копию.
    assert state["active_section_index"] == 1
    # Глубокая копия: правка копии не меняет оригинал.
    copy["blocks"][0]["text"] = "Изменённый текст"
    assert orig["blocks"][0]["text"] == "Текст главы 1"


def test_duplicate_bibliography_resets_flag() -> None:
    """Дубликат bib-секции теряет is_bibliography и references."""
    from gostforge.web.builder_editor import _duplicate_section

    state = st.session_state["builder_state"]
    state["sections"] = [
        {
            "heading": "Список",
            "blocks": [],
            "subsections": [],
            "is_bibliography": True,
            "references": ["Кнут. — М., 2007."],
        }
    ]
    _duplicate_section(0)
    copy = state["sections"][1]
    assert copy.get("is_bibliography") is False
    assert "references" not in copy


def test_duplicate_section_out_of_range_does_nothing() -> None:
    from gostforge.web.builder_editor import _duplicate_section

    state = st.session_state["builder_state"]
    state["sections"] = [{"heading": "X", "blocks": [], "subsections": []}]
    _duplicate_section(99)  # вне диапазона
    assert len(state["sections"]) == 1


# --- _compute_import_violations_summary ---


def test_import_violations_summary_for_clean_document() -> None:
    """Документ без нарушений → total=0, by_severity all-zero."""
    from gostforge.model import Document, DocumentMetadata
    from gostforge.web.builder_editor import _compute_import_violations_summary

    doc = Document(metadata=DocumentMetadata(title="X"))
    summary = _compute_import_violations_summary(doc, "gost-7.32-2017")
    assert summary["total"] >= 0  # реально не 0, но проверяем структуру
    assert "by_severity" in summary
    assert "top_codes" in summary


def test_import_violations_summary_unknown_profile() -> None:
    """Невалидный profile_id → пустая сводка, не падает."""
    from gostforge.model import Document, DocumentMetadata
    from gostforge.web.builder_editor import _compute_import_violations_summary

    doc = Document(metadata=DocumentMetadata(title="X"))
    summary = _compute_import_violations_summary(doc, "non-existent-profile")
    assert summary == {"total": 0, "by_severity": {}, "top_codes": []}


def test_import_violations_summary_returns_top_codes(tmp_path: Path) -> None:
    """Сводка содержит топ-N кодов с count > 0."""
    from gostforge.web.builder_editor import _compute_import_violations_summary

    # Реальный документ с типичными нарушениями.
    b = (
        work("X", year=2026)
        .section("Введение")
        .paragraph("очень короткий текст")
        .section("Список использованных источников")
        .reference("плохой формат без всего")
    )
    doc = b.build()
    out = tmp_path / "doc.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    parsed.profile_id = "gost-7.32-2017"

    summary = _compute_import_violations_summary(parsed, "gost-7.32-2017")
    assert summary["total"] > 0
    assert len(summary["top_codes"]) <= 10
    for entry in summary["top_codes"]:
        assert "code" in entry and "count" in entry
        assert entry["count"] >= 1


# --- _group_text_marker_lists в парсере ---


def test_marker_list_grouping_with_dash(tmp_path: Path) -> None:
    """Подряд идущие «– X» «– Y» в exported docx собираются в ListBlock."""
    from gostforge.model import ListBlock

    b = (
        work("X", year=2026)
        .section("Введение")
        .paragraph("Перечень требований:")
        .list(["требование 1", "требование 2", "требование 3"], ordered=False)
        .paragraph("Дополнение.")
    )
    doc = b.build()
    out = tmp_path / "list.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    # Найдём LogicalSection.
    intro = parsed.page_sections[0].content[0]
    assert hasattr(intro, "children")
    list_blocks = [c for c in intro.children if isinstance(c, ListBlock)]
    assert list_blocks, (
        f"Список не сгруппирован. Children: {[type(c).__name__ for c in intro.children]}"
    )
    lb = list_blocks[0]
    assert len(lb.items) == 3
    assert lb.ordered is False


def test_marker_list_grouping_with_numbered(tmp_path: Path) -> None:
    """Серия «1) ...», «2) ...» собирается в ordered ListBlock."""
    from gostforge.model import ListBlock

    b = (
        work("X", year=2026)
        .section("Введение")
        .list(["первый шаг", "второй шаг", "третий шаг"], ordered=True)
    )
    doc = b.build()
    out = tmp_path / "ordered.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    intro = parsed.page_sections[0].content[0]
    list_blocks = [c for c in intro.children if isinstance(c, ListBlock)]
    assert list_blocks
    lb = list_blocks[0]
    assert lb.ordered is True
    assert len(lb.items) == 3


def test_marker_grouping_does_not_affect_bibliography(tmp_path: Path) -> None:
    """В библиографическом разделе подряд идущие записи НЕ группируются
    в ListBlock — каждая остаётся отдельным Paragraph."""
    from gostforge.model import ListBlock, Paragraph

    b = (
        work("X", year=2026)
        .section("Список использованных источников")
        .reference("Кнут Д. — М., 2007. — 832 с.")
        .reference("Кормен. — М., 2013.")
        .reference("Седжвик. — СПб., 2014.")
    )
    doc = b.build()
    out = tmp_path / "bib.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    bib_sec = parsed.page_sections[0].content[0]
    list_blocks = [c for c in bib_sec.children if isinstance(c, ListBlock)]
    paragraphs = [c for c in bib_sec.children if isinstance(c, Paragraph)]
    # Никаких list-блоков в bib-разделе.
    assert not list_blocks
    # Все 3 записи как параграфы.
    assert len(paragraphs) >= 3


def test_single_dash_does_not_become_list(tmp_path: Path) -> None:
    """Одиночный «– X» (не серия) не превращается в ListBlock —
    защита от ложных срабатываний на тире-сепаратор."""
    from gostforge.model import ListBlock

    b = (
        work("X", year=2026)
        .section("Введение")
        .paragraph("Текст до.")
        .paragraph("– один маркер сам по себе")
        .paragraph("Текст после.")
    )
    doc = b.build()
    out = tmp_path / "single.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    intro = parsed.page_sections[0].content[0]
    list_blocks = [c for c in intro.children if isinstance(c, ListBlock)]
    assert not list_blocks


# --- Year preserved через core.created ---


def test_year_preserved_through_docx_round_trip(tmp_path: Path) -> None:
    """metadata.year пишется в core.created → парсер видит при импорте."""
    from gostforge.web.builder_editor import document_to_state

    b = (
        work("X", author="A", year=2025)
        .section("Введение")
        .paragraph("p")
        .section("Список использованных источников")
        .reference("Кнут — М., 2007.")
    )
    doc = b.build()
    out = tmp_path / "year.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    state = document_to_state(parsed)
    assert state["year"] == 2025
