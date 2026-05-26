# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты helpers и сборки документов с inline-элементами (шаг 6 Фазы 2.5).

Покрытие:
- _collect_xref_targets — сбор figure/table/formula по разделам.
- _collect_bibliography_options — список proxy bib-N с лейблами.
- _resolve_citation_proxies — замена bib-N на реальный source_id.
- Полный путь: state с Citation(bib-1) → build → resolve → export → парс →
  Citation в модели с реальным id.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("streamlit")

from gostforge.builder import work
from gostforge.model import (
    BibliographyEntry,
    Citation,
    Document,
    InlineFormula,
    LogicalSection,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.web.builder_editor import (
    _build_document_from_state,
    _collect_bibliography_options,
    _collect_xref_targets,
    _resolve_citation_proxies,
)


# --- _collect_xref_targets --------------------------------------------------


def test_collect_xref_targets_picks_up_figures_in_order() -> None:
    """Рисунки нумеруются по порядку обхода, в id используется fig-N."""
    state: dict[str, Any] = {
        "sections": [
            {
                "id": "s1",
                "heading": "Глава 1",
                "blocks": [
                    {"kind": "figure", "image_path": "", "caption": "первый"},
                    {"kind": "figure", "image_path": "", "caption": "второй"},
                ],
                "subsections": [],
            }
        ]
    }
    targets = _collect_xref_targets(state)
    assert [t[0] for t in targets] == ["fig-1", "fig-2"]
    assert "первый" in targets[0][1]


def test_collect_xref_targets_collects_tables_and_formulas() -> None:
    """Таблицы → tbl-N, нумерованные формулы → formula-N."""
    state: dict[str, Any] = {
        "sections": [
            {
                "id": "s1",
                "heading": "Глава",
                "blocks": [
                    {"kind": "table", "headers": ["a"], "rows": [], "caption": "T1"},
                    {"kind": "formula", "latex": "x^2", "numbered": True},
                    {"kind": "formula", "latex": "y", "numbered": False},
                ],
                "subsections": [],
            }
        ]
    }
    targets = _collect_xref_targets(state)
    values = [t[0] for t in targets]
    # numbered=False формула не должна попасть в xref-цели.
    assert values == ["tbl-1", "formula-1"]


def test_collect_xref_targets_descends_into_subsections() -> None:
    state: dict[str, Any] = {
        "sections": [
            {
                "id": "s1",
                "heading": "Глава",
                "blocks": [],
                "subsections": [
                    {
                        "id": "s1.1",
                        "heading": "1.1",
                        "blocks": [{"kind": "figure", "image_path": "", "caption": "вложенный"}],
                    }
                ],
            }
        ]
    }
    targets = _collect_xref_targets(state)
    assert targets == [("fig-1", "Рисунок 1: вложенный")]


def test_collect_xref_targets_skips_bibliography_section() -> None:
    """Раздел библиографии не содержит фигур, но если кто-то их туда положит — игнор."""
    state: dict[str, Any] = {
        "sections": [
            {
                "id": "ref",
                "heading": "Список",
                "is_bibliography": True,
                "blocks": [{"kind": "figure", "image_path": "", "caption": "не считаем"}],
                "subsections": [],
            }
        ]
    }
    assert _collect_xref_targets(state) == []


# --- _collect_bibliography_options -----------------------------------------


def test_collect_bibliography_options_returns_bib_n_proxies() -> None:
    state: dict[str, Any] = {
        "sections": [
            {
                "id": "ref",
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "blocks": [],
                "subsections": [],
                "references": [
                    "Иванов И. И. Программирование. — М. : Наука, 2023. — 320 с.",
                    "Петров П. П. Алгоритмы. — СПб. : Лань, 2024. — 200 с.",
                    "",  # пустой ref должен быть отфильтрован
                ],
            }
        ]
    }
    options = _collect_bibliography_options(state)
    assert [v for v, _ in options] == ["bib-1", "bib-2"]
    assert options[0][1].startswith("[1] Иванов")


def test_collect_bibliography_options_no_section_returns_empty() -> None:
    """Если нет раздела с is_bibliography — пустой список."""
    state: dict[str, Any] = {
        "sections": [{"id": "s1", "heading": "Глава", "blocks": [], "subsections": []}]
    }
    assert _collect_bibliography_options(state) == []


# --- _resolve_citation_proxies ---------------------------------------------


def test_resolve_citation_proxies_replaces_bib_n_with_real_id() -> None:
    """bib-1 → bibliography[0].id; bib-2 → bibliography[1].id."""
    doc = Document(
        bibliography=[
            BibliographyEntry(id="ref:book-1", type="book", fields={}),
            BibliographyEntry(id="ref:web-1", type="web", fields={}),
        ],
        page_sections=[
            PageSection(
                id="main",
                name="m",
                type="main",
                content=[
                    Paragraph(
                        id="p1",
                        content=[
                            TextRun(text="См. "),
                            Citation(source_id="bib-1"),
                            TextRun(text=" и "),
                            Citation(source_id="bib-2", pages="42"),
                        ],
                    )
                ],
            )
        ],
    )
    _resolve_citation_proxies(doc, state={})
    cites = [el for el in doc.page_sections[0].content[0].content if isinstance(el, Citation)]
    assert cites[0].source_id == "ref:book-1"
    assert cites[1].source_id == "ref:web-1"
    assert cites[1].pages == "42"  # pages не трогаем


def test_resolve_citation_proxies_ignores_non_bib_prefixed_ids() -> None:
    """Если source_id уже реальный (не bib-N) — оставляем как есть."""
    doc = Document(
        bibliography=[BibliographyEntry(id="some-id", type="book", fields={})],
        page_sections=[
            PageSection(
                id="main",
                name="m",
                type="main",
                content=[
                    Paragraph(
                        id="p1",
                        content=[Citation(source_id="custom-id")],
                    )
                ],
            )
        ],
    )
    _resolve_citation_proxies(doc, state={})
    cite = doc.page_sections[0].content[0].content[0]
    assert isinstance(cite, Citation)
    assert cite.source_id == "custom-id"


def test_resolve_citation_proxies_keeps_invalid_index_unchanged() -> None:
    """bib-99 при библиографии из 2 записей не должен меняться."""
    doc = Document(
        bibliography=[
            BibliographyEntry(id="a", type="book", fields={}),
            BibliographyEntry(id="b", type="book", fields={}),
        ],
        page_sections=[
            PageSection(
                id="main",
                name="m",
                type="main",
                content=[
                    Paragraph(id="p", content=[Citation(source_id="bib-99")]),
                ],
            )
        ],
    )
    _resolve_citation_proxies(doc, state={})
    cite = doc.page_sections[0].content[0].content[0]
    assert isinstance(cite, Citation)
    assert cite.source_id == "bib-99"  # не тронут


def test_resolve_citation_proxies_descends_into_logical_sections() -> None:
    """Рекурсия должна заходить в LogicalSection.children."""
    doc = Document(
        bibliography=[BibliographyEntry(id="real", type="book", fields={})],
        page_sections=[
            PageSection(
                id="main",
                name="m",
                type="main",
                content=[
                    LogicalSection(
                        id="sec1",
                        heading=[TextRun(text="Глава")],
                        children=[Paragraph(id="p", content=[Citation(source_id="bib-1")])],
                    )
                ],
            )
        ],
    )
    _resolve_citation_proxies(doc, state={})
    section = doc.page_sections[0].content[0]
    assert isinstance(section, LogicalSection)
    para = section.children[0]
    assert isinstance(para, Paragraph)
    cite = para.content[0]
    assert isinstance(cite, Citation)
    assert cite.source_id == "real"


# --- Сборка документа из state с citation-proxy ----------------------------


def test_build_from_state_resolves_bib_proxy_at_export() -> None:
    """End-to-end: bib-1 в state → реальный source_id в собранном .docx."""
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
                            {"kind": "text", "text": "Это подтверждается в "},
                            {
                                "kind": "citation",
                                "source_id": "bib-1",
                                "pages": "42",
                                "template": "[{n}, с. {pages}]",
                            },
                            {"kind": "text", "text": "."},
                        ],
                    }
                ],
                "subsections": [],
            },
            {
                "id": "ref",
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "blocks": [],
                "subsections": [],
                "references": [
                    "Иванов И. И. Программирование. — М. : Наука, 2023. — 320 с.",
                ],
            },
        ],
    }
    data = _build_document_from_state(state)
    # В docx-тексте должна появиться итоговая «[1, с. 42]»
    # (а не «[?, с. 42]», что было бы при невалидной resolve).
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "[1, с. 42]" in xml


# --- Round-trip с InlineFormula ---------------------------------------------


def test_build_from_state_inline_formula_survives_to_docx() -> None:
    """InlineFormula в state → m:oMath внутри w:r в собранном .docx."""
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
                            {"kind": "text", "text": "Энергия "},
                            {"kind": "formula", "latex": "E = h\\nu"},
                            {"kind": "text", "text": "."},
                        ],
                    }
                ],
                "subsections": [],
            }
        ],
    }
    data = _build_document_from_state(state)
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "oMath" in xml
    assert "E = h" in xml  # хотя бы фрагмент latex


def test_collect_xref_targets_empty_state_returns_empty_list() -> None:
    assert _collect_xref_targets({}) == []
    assert _collect_xref_targets({"sections": []}) == []
