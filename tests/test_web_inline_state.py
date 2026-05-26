"""Тесты конвертеров inline-элементов между моделью и state Фазы 2.5.

Покрытие:
- _inline_to_run_dict / _run_dict_to_inline — round-trip всех 4 типов
- _normalize_paragraph_state — миграция legacy формата text → runs
- _normalize_state_paragraphs — рекурсивная миграция по разделам
- _apply_blocks — поддержка обоих форматов на стороне сборки
- сериализация Document → state — параграфы выходят в формате runs
- сквозной round-trip: state → Document → state
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("streamlit")

from gostforge.builder import work
from gostforge.model import (
    Citation,
    CrossRef,
    InlineFormula,
    TextRun,
)
from gostforge.web.builder_editor import (
    _build_document_from_state,
    _document_to_state,
    _inline_to_run_dict,
    _normalize_paragraph_state,
    _normalize_state_paragraphs,
    _run_dict_to_inline,
    _runs_from_inline,
    _runs_to_inline,
)

# --- Базовая сериализация одного inline-элемента ----------------------------


def test_text_run_minimal_to_dict() -> None:
    """TextRun без форматирования — только text-поле."""
    run = TextRun(text="Привет")
    assert _inline_to_run_dict(run) == {"kind": "text", "text": "Привет"}


def test_text_run_with_formatting_to_dict() -> None:
    """Bold/italic/underline/font попадают в dict, None-поля опускаются."""
    run = TextRun(
        text="x",
        bold=True,
        italic=False,
        underline=True,
        font="Times New Roman",
        size_pt=14.0,
        color_hex="#FF0000",
    )
    d = _inline_to_run_dict(run)
    assert d == {
        "kind": "text",
        "text": "x",
        "bold": True,
        "italic": False,
        "underline": True,
        "font": "Times New Roman",
        "size_pt": 14.0,
        "color_hex": "#FF0000",
    }


def test_cross_ref_to_dict_default_template_omitted() -> None:
    """Default display_template не пишется в dict — для краткости."""
    ref = CrossRef(target_id="fig-1", prefix=" (см. ")
    assert _inline_to_run_dict(ref) == {
        "kind": "xref",
        "target_id": "fig-1",
        "prefix": " (см. ",
    }


def test_inline_formula_to_dict() -> None:
    f = InlineFormula(latex=r"h\nu")
    assert _inline_to_run_dict(f) == {"kind": "formula", "latex": r"h\nu"}


def test_citation_to_dict_minimal() -> None:
    c = Citation(source_id="iv-23")
    assert _inline_to_run_dict(c) == {"kind": "citation", "source_id": "iv-23"}


def test_citation_to_dict_with_pages_and_template() -> None:
    c = Citation(
        source_id="iv-23",
        pages="42",
        template="[{n}, с. {pages}]",
    )
    assert _inline_to_run_dict(c) == {
        "kind": "citation",
        "source_id": "iv-23",
        "pages": "42",
        "template": "[{n}, с. {pages}]",
    }


# --- Обратная конвертация dict → InlineElement -----------------------------


def test_run_dict_to_inline_text_basic() -> None:
    el = _run_dict_to_inline({"kind": "text", "text": "hi", "bold": True})
    assert isinstance(el, TextRun)
    assert el.text == "hi"
    assert el.bold is True
    assert el.italic is None  # не задано → None


def test_run_dict_to_inline_text_missing_text_returns_none() -> None:
    """Невалидный text-run без поля text игнорируется."""
    assert _run_dict_to_inline({"kind": "text"}) is None


def test_run_dict_to_inline_xref_returns_cross_ref() -> None:
    el = _run_dict_to_inline({"kind": "xref", "target_id": "tbl-1", "prefix": "см. "})
    assert isinstance(el, CrossRef)
    assert el.target_id == "tbl-1"
    assert el.prefix == "см. "


def test_run_dict_to_inline_formula_returns_inline_formula() -> None:
    el = _run_dict_to_inline({"kind": "formula", "latex": "x^2"})
    assert isinstance(el, InlineFormula)
    assert el.latex == "x^2"


def test_run_dict_to_inline_citation_returns_citation() -> None:
    el = _run_dict_to_inline({"kind": "citation", "source_id": "abc", "pages": "5"})
    assert isinstance(el, Citation)
    assert el.source_id == "abc"
    assert el.pages == "5"


def test_run_dict_unknown_kind_returns_none() -> None:
    assert _run_dict_to_inline({"kind": "alien", "x": 1}) is None


# --- Round-trip: list[InlineElement] ↔ list[dict] --------------------------


def test_round_trip_mixed_inline_elements() -> None:
    """Полный набор inline-элементов выживает прогон туда и обратно."""
    original: list[Any] = [
        TextRun(text="Энергия ", bold=False),
        InlineFormula(latex=r"E = h\nu"),
        TextRun(text=" описана в "),
        Citation(source_id="planck-1900", pages="42"),
        TextRun(text=" (см. "),
        CrossRef(target_id="fig-1", prefix=""),
        TextRun(text=")."),
    ]
    runs = _runs_from_inline(original)
    restored = _runs_to_inline(runs)
    # Длина и порядок типов совпадают.
    assert [type(x).__name__ for x in restored] == [type(x).__name__ for x in original]
    # Текст / ключевые поля совпадают.
    assert restored[0] == TextRun(text="Энергия ", bold=False)
    assert restored[1] == InlineFormula(latex=r"E = h\nu")
    assert restored[3] == Citation(source_id="planck-1900", pages="42")


# --- Нормализация legacy paragraph (text → runs) ---------------------------


def test_normalize_paragraph_state_converts_text_to_runs() -> None:
    block: dict[str, Any] = {"kind": "paragraph", "text": "Привет"}
    _normalize_paragraph_state(block)
    assert "text" not in block
    assert block["runs"] == [{"kind": "text", "text": "Привет"}]


def test_normalize_paragraph_state_empty_text_yields_empty_runs() -> None:
    block: dict[str, Any] = {"kind": "paragraph", "text": ""}
    _normalize_paragraph_state(block)
    assert block["runs"] == []
    assert "text" not in block


def test_normalize_paragraph_state_no_text_no_runs_yields_empty() -> None:
    block: dict[str, Any] = {"kind": "paragraph"}
    _normalize_paragraph_state(block)
    assert block["runs"] == []


def test_normalize_paragraph_state_keeps_existing_runs() -> None:
    """Если runs уже есть — функция их не трогает (идемпотентна)."""
    runs = [{"kind": "text", "text": "уже"}, {"kind": "formula", "latex": "x"}]
    block: dict[str, Any] = {"kind": "paragraph", "runs": runs, "text": "должно уйти"}
    _normalize_paragraph_state(block)
    assert block["runs"] == runs
    assert "text" not in block


def test_normalize_paragraph_state_skips_non_paragraph() -> None:
    """Таблицы/рисунки/списки не модифицируются."""
    block: dict[str, Any] = {"kind": "table", "headers": ["a"], "rows": []}
    snapshot = dict(block)
    _normalize_paragraph_state(block)
    assert block == snapshot


def test_normalize_state_paragraphs_recurses_into_subsections() -> None:
    """Параграфы в подразделах тоже нормализуются."""
    state: dict[str, Any] = {
        "sections": [
            {
                "id": "s1",
                "heading": "Глава 1",
                "blocks": [{"kind": "paragraph", "text": "верхний"}],
                "subsections": [
                    {
                        "id": "s1.1",
                        "heading": "1.1",
                        "blocks": [
                            {"kind": "paragraph", "text": "вложенный"},
                            {"kind": "list", "items": ["x"], "ordered": False},
                        ],
                    }
                ],
            }
        ]
    }
    _normalize_state_paragraphs(state)
    top = state["sections"][0]["blocks"][0]
    assert top["runs"] == [{"kind": "text", "text": "верхний"}]
    sub = state["sections"][0]["subsections"][0]["blocks"][0]
    assert sub["runs"] == [{"kind": "text", "text": "вложенный"}]
    # Не-параграф остался нетронутым.
    assert state["sections"][0]["subsections"][0]["blocks"][1]["kind"] == "list"


# --- _apply_blocks принимает оба формата -----------------------------------


def test_build_from_legacy_text_format_still_works() -> None:
    """Параграф со старым text=... строится так же, как раньше."""
    state: dict[str, Any] = {
        "title": "T",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "s1",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "legacy"}],
                "subsections": [],
            }
        ],
    }
    data = _build_document_from_state(state)
    assert data.startswith(b"PK")  # zip-сигнатура .docx


def test_build_from_new_runs_format_uses_rich_paragraph() -> None:
    """Параграф с runs=[...] прокидывается через rich_paragraph и доходит до docx."""
    state: dict[str, Any] = {
        "title": "T",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "s1",
                "heading": "Введение",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "runs": [
                            {"kind": "text", "text": "Жирный кусок ", "bold": True},
                            {"kind": "text", "text": "обычный."},
                        ],
                    }
                ],
                "subsections": [],
            }
        ],
    }
    data = _build_document_from_state(state)
    assert data.startswith(b"PK")


# --- Document → state теперь пишет runs ------------------------------------


def test_document_to_state_writes_paragraph_as_runs() -> None:
    """Сериализация Document → state кладёт параграфы в схему runs."""
    doc = (
        work("T")
        .section("Введение")
        .rich_paragraph(
            [
                TextRun(text="Простой "),
                TextRun(text="жирный", bold=True),
            ]
        )
        .build()
    )
    state = _document_to_state(doc)
    para = state["sections"][0]["blocks"][0]
    assert para["kind"] == "paragraph"
    assert "text" not in para
    assert para["runs"] == [
        {"kind": "text", "text": "Простой "},
        {"kind": "text", "text": "жирный", "bold": True},
    ]


def test_round_trip_state_document_state_preserves_runs() -> None:
    """state → Document → state идемпотентен на простом параграфе."""
    state_in: dict[str, Any] = {
        "title": "T",
        "author": "",
        "supervisor": "",
        "organization": "",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "active_section_index": 0,
        "sections": [
            {
                "id": "s1",
                "heading": "Введение",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "runs": [
                            {"kind": "text", "text": "часть 1 "},
                            {"kind": "text", "text": "часть 2"},
                        ],
                    }
                ],
                "subsections": [],
            }
        ],
    }
    # Через builder соберём документ напрямую — без парсера, чтобы
    # round-trip покрывал только state↔Document, без OOXML.
    from gostforge.web.builder_editor import _apply_blocks  # локальный импорт

    builder = work(title="T", year=2026).section("Введение")
    _apply_blocks(builder, state_in["sections"][0]["blocks"])
    doc = builder.build()
    state_out = _document_to_state(doc)
    runs = state_out["sections"][0]["blocks"][0]["runs"]
    assert runs == [
        {"kind": "text", "text": "часть 1 "},
        {"kind": "text", "text": "часть 2"},
    ]
