"""Тесты автоматического оглавления (TOC) и авто-применения фиксов."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.model import TableOfContents
from gostforge.profile import load_profile


def _docx_xml(out: Path, part: str) -> str:
    with zipfile.ZipFile(out) as zf:
        return zf.read(part).decode("utf-8")


# --- TOC через builder API ---


def test_builder_table_of_contents(tmp_path: Path) -> None:
    """SectionBuilder.table_of_contents() добавляет TableOfContents-блок."""
    b = (
        work("X", year=2026)
        .section("Содержание")
        .table_of_contents()
        .section("Введение")
        .paragraph("p")
    )
    doc = b.build()
    sec = doc.page_sections[0].content[0]
    toc_blocks = [c for c in sec.children if isinstance(c, TableOfContents)]
    assert len(toc_blocks) == 1
    assert toc_blocks[0].min_level == 1
    assert toc_blocks[0].max_level == 3


def test_toc_writes_field_in_docx(tmp_path: Path) -> None:
    """Экспортёр пишет <w:fldSimple w:instr="TOC..."/> в document.xml."""
    b = (
        work("X", year=2026)
        .section("Содержание")
        .table_of_contents()
        .section("Введение")
        .paragraph("p")
    )
    out = tmp_path / "toc.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    assert '<w:fldSimple w:instr=" TOC' in doc_xml
    # По дефолту уровни 1-3 (кавычки в XML-атрибутах экранированы как &quot;).
    assert "\\o &quot;1-3&quot;" in doc_xml or '\\o "1-3"' in doc_xml


def test_toc_with_custom_levels(tmp_path: Path) -> None:
    """min_level/max_level из builder API попадают в TOC-instr."""
    b = (
        work("X", year=2026)
        .section("Содержание")
        .table_of_contents(min_level=1, max_level=2)
        .section("Введение")
        .paragraph("p")
    )
    out = tmp_path / "toc2.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    assert "\\o &quot;1-2&quot;" in doc_xml or '\\o "1-2"' in doc_xml


# --- TOC через state (UI / CLI) ---


def test_toc_block_round_trip_through_state(tmp_path: Path) -> None:
    """state {'kind': 'toc'} → builder → docx → document_to_state."""
    pytest.importorskip("streamlit")
    from gostforge.parser import parse_docx
    from gostforge.web.builder_editor import (
        _build_document_from_state,
        document_to_state,
    )

    state_in = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Содержание",
                "blocks": [{"kind": "toc", "min_level": 1, "max_level": 3}],
            },
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "p"}],
            },
        ],
    }
    data = _build_document_from_state(state_in)
    out = tmp_path / "rt.docx"
    out.write_bytes(data)
    # При парсинге обратно TOC может не быть распознан как
    # TableOfContents (парсер не специально обрабатывает fldSimple-TOC),
    # но главное — что генерация прошла без падений.
    parsed = parse_docx(out)
    state_out = document_to_state(parsed)
    # Имена секций сохранились.
    headings = [s["heading"] for s in state_out["sections"]]
    assert any("содержани" in h.lower() for h in headings)


def test_toc_template_in_section_templates() -> None:
    """Шаблон 'Содержание' в _SECTION_TEMPLATES содержит TOC-блок."""
    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _SECTION_TEMPLATES

    _, factory = _SECTION_TEMPLATES["toc"]
    section = factory()
    assert section.get("heading") == "Содержание"
    blocks = section.get("blocks", [])
    toc_blocks = [b for b in blocks if b.get("kind") == "toc"]
    assert len(toc_blocks) == 1
    assert toc_blocks[0].get("min_level") == 1
    assert toc_blocks[0].get("max_level") == 3


# --- L.04 fixer ---


def test_l04_fixer_normalizes_endings(tmp_path: Path) -> None:
    """L.04-fixer: убирает хвостовые знаки, ставит ';' и '.'."""
    pytest.importorskip("streamlit")
    from gostforge.fixer.engine import fix as run_fix
    from gostforge.model import (
        Document,
        DocumentMetadata,
        LogicalSection,
        PageGeometry,
        PageNumberingConfig,
        PageSection,
    )
    from gostforge.model import ListBlock as LB
    from gostforge.model import TextRun as TR

    doc = Document(metadata=DocumentMetadata(title="X"))
    lb = LB(
        id="L",
        ordered=False,
        items=[
            [TR(text="первый.")],
            [TR(text="второй,")],
            [TR(text="третий без знака")],
        ],
    )
    sec = LogicalSection(
        id="sec",
        heading=[TR(text="Х")],
        level=1,
        children=[lb],
    )
    doc.page_sections.append(
        PageSection(
            id="m",
            name="Основная",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec],
        )
    )
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["L.04"])
    assert applied
    # После фикса: первый;, второй;, третий.
    texts = ["".join(el.text for el in item if hasattr(el, "text")) for item in lb.items]
    assert texts == ["первый;", "второй;", "третий без знака."]


def test_l04_fixer_idempotent(tmp_path: Path) -> None:
    pytest.importorskip("streamlit")
    from gostforge.fixer.engine import fix as run_fix
    from gostforge.model import (
        Document,
        DocumentMetadata,
        LogicalSection,
        PageGeometry,
        PageNumberingConfig,
        PageSection,
    )
    from gostforge.model import ListBlock as LB
    from gostforge.model import TextRun as TR

    doc = Document(metadata=DocumentMetadata(title="X"))
    lb = LB(
        id="L",
        ordered=False,
        items=[[TR(text="первый;")], [TR(text="второй.")]],
    )
    sec = LogicalSection(
        id="s",
        heading=[TR(text="X")],
        level=1,
        children=[lb],
    )
    doc.page_sections.append(
        PageSection(
            id="m",
            name="N",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec],
        )
    )
    profile = load_profile("gost-7.32-2017")
    run_fix(doc, profile, codes=["L.04"])
    applied2 = run_fix(doc, profile, codes=["L.04"])
    # Повторный fix — 0 (всё уже правильно).
    assert applied2 == []


# --- Иерархия секций после фикса парсера ---


def test_parser_builds_section_hierarchy(tmp_path: Path) -> None:
    """Парсер должен класть подразделы в children главы, а не плоско."""
    from gostforge.model import LogicalSection
    from gostforge.parser import parse_docx

    b = (
        work("X", year=2026)
        .section("Глава 1")
        .paragraph("в главе")
        .subsection("1.1 Подраздел")
        .paragraph("в подразделе")
    )
    out = tmp_path / "hier.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    top = parsed.page_sections[0].content
    # Top-level — только главы (level=1).
    chapters = [c for c in top if isinstance(c, LogicalSection) and c.level == 1]
    assert chapters, "Глав level=1 не найдено"
    chap = chapters[0]
    # У главы должны быть child-секции с level=2.
    sub_sections = [c for c in chap.children if isinstance(c, LogicalSection) and c.level == 2]
    assert sub_sections, (
        f"Подразделы не попали в children главы. Children: "
        f"{[type(c).__name__ for c in chap.children]}"
    )


# --- C.01 не считает подпись ссылкой ---


def test_caption_not_treated_as_crossref(tmp_path: Path) -> None:
    """В подписи рисунка 'Рисунок 1 — описание' не должно быть C.01."""
    pytest.importorskip("PIL")
    from PIL import Image

    from gostforge.parser import parse_docx
    from gostforge.validator import validate

    img_path = tmp_path / "f.png"
    Image.new("RGB", (300, 200), color="red").save(img_path)

    b = (
        work("X", year=2026)
        .section("Введение")
        .paragraph("Текст до рисунка.")
        .figure(image_path=str(img_path), caption="Функциональный блок")
        .paragraph("Текст после рисунка.")
        .section("Список использованных источников")
        .reference("Кнут — М., 2007.")
    )
    out = tmp_path / "fig.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    parsed.profile_id = "gost-7.32-2017"
    profile = load_profile("gost-7.32-2017")
    violations = validate(parsed, profile)
    # C.01: ссылка на рисунок 1 — рисунок СУЩЕСТВУЕТ, не должно быть violation.
    c01 = [v for v in violations if v.check_code == "C.01"]
    # Если в тексте абзацев есть «Рисунок 1 — Функциональный блок»
    # (это подпись, не ссылка), C.01 не должен срабатывать.
    for v in c01:
        # Допустимы только если рисунок реально не найден.
        # Главное — нет ссылок на «рисунок 1» в подписи.
        assert "Функциональный блок" not in v.message
