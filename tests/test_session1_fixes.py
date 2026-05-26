# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты сессии 1 плана развития:
* F.06, F.04, H.04 автофиксеры;
* live-preview TOC в UI;
* шаблоны блоков _BLOCK_TEMPLATES.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gostforge.fixer.engine import fix as run_fix
from gostforge.model import (
    ContentTemplate,
    Document,
    DocumentMetadata,
    HeaderConfig,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    TextRun,
)
from gostforge.profile import load_profile


# --- F.06 fixer ---


def test_f06_fixer_sets_start_value() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    ps = PageSection(
        id="m",
        name="N",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True, start_mode="start_at", start_value=1),
    )
    doc.page_sections.append(ps)
    profile = load_profile("gost-r-2.105-2019")  # F.06.start_value = 2
    applied = run_fix(doc, profile, codes=["F.06"])
    assert len(applied) == 1
    assert ps.page_numbering.start_value == 2


def test_f06_fixer_skips_invisible_numbering() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.page_sections.append(
        PageSection(
            id="m",
            name="N",
            type="title",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(visible=False),
        )
    )
    profile = load_profile("gost-r-2.105-2019")
    applied = run_fix(doc, profile, codes=["F.06"])
    assert applied == []


def test_f06_fixer_idempotent() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    ps = PageSection(
        id="m",
        name="N",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(
            visible=True,
            start_mode="start_at",
            start_value=2,
        ),
    )
    doc.page_sections.append(ps)
    profile = load_profile("gost-r-2.105-2019")
    applied = run_fix(doc, profile, codes=["F.06"])
    assert applied == []  # уже = 2


# --- F.04 fixer ---


def test_f04_fixer_places_page_in_bottom_center() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    ps = PageSection(
        id="m",
        name="N",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True),
        footer=HeaderConfig(default=ContentTemplate()),
    )
    doc.page_sections.append(ps)
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["F.04"])
    assert len(applied) == 1
    center = ps.footer.default.center
    assert center
    assert any(isinstance(el, TextRun) and el.text == "{page}" for el in center)


def test_f04_fixer_moves_page_from_left_to_center() -> None:
    """Если {page} был в left — переносим в center."""
    doc = Document(metadata=DocumentMetadata(title="X"))
    ps = PageSection(
        id="m",
        name="N",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True),
        footer=HeaderConfig(default=ContentTemplate(left=[TextRun(text="{page}")])),
    )
    doc.page_sections.append(ps)
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["F.04"])
    assert len(applied) == 1
    # Левый слот пуст, центр имеет {page}.
    assert not any(
        isinstance(el, TextRun) and el.text == "{page}" for el in (ps.footer.default.left or [])
    )
    assert any(
        isinstance(el, TextRun) and el.text == "{page}" for el in (ps.footer.default.center or [])
    )


def test_f04_fixer_idempotent() -> None:
    """Если {page} уже в нужном слоте — no-op."""
    doc = Document(metadata=DocumentMetadata(title="X"))
    ps = PageSection(
        id="m",
        name="N",
        type="main",
        page=PageGeometry(),
        page_numbering=PageNumberingConfig(visible=True),
        footer=HeaderConfig(default=ContentTemplate(center=[TextRun(text="{page}")])),
    )
    doc.page_sections.append(ps)
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["F.04"])
    assert applied == []


# --- H.04 fixer ---


def _make_doc_with_chapters() -> Document:
    doc = Document(metadata=DocumentMetadata(title="X"))
    sec1 = LogicalSection(id="s1", heading=[TextRun(text="Введение")], level=1)
    sec2 = LogicalSection(id="s2", heading=[TextRun(text="Анализ")], level=1)
    sub21 = LogicalSection(
        id="s2.1",
        heading=[TextRun(text="Постановка задачи")],
        level=2,
    )
    sub22 = LogicalSection(
        id="s2.2",
        heading=[TextRun(text="Существующие решения")],
        level=2,
    )
    sec2.children = [sub21, sub22]
    sec3 = LogicalSection(id="s3", heading=[TextRun(text="Проектирование")], level=1)
    sec4 = LogicalSection(id="s4", heading=[TextRun(text="Заключение")], level=1)
    doc.page_sections.append(
        PageSection(
            id="m",
            name="N",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec1, sec2, sec3, sec4],
        )
    )
    return doc


def _heading_text(sec: LogicalSection) -> str:
    return "".join(el.text for el in sec.heading if isinstance(el, TextRun))


def test_h04_fixer_numbers_chapters_skipping_structural() -> None:
    """Введение и Заключение не нумеруются; Анализ → '1', Проектирование → '2'."""
    doc = _make_doc_with_chapters()
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["H.04"].enabled = True
    run_fix(doc, profile, codes=["H.04"])
    sections = doc.page_sections[0].content
    assert _heading_text(sections[0]) == "Введение"
    assert _heading_text(sections[1]) == "1 Анализ"
    assert _heading_text(sections[2]) == "2 Проектирование"
    assert _heading_text(sections[3]) == "Заключение"


def test_h04_fixer_numbers_subsections() -> None:
    doc = _make_doc_with_chapters()
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["H.04"].enabled = True
    run_fix(doc, profile, codes=["H.04"])
    sec2 = doc.page_sections[0].content[1]
    subs = sec2.children
    assert _heading_text(subs[0]) == "1.1 Постановка задачи"
    assert _heading_text(subs[1]) == "1.2 Существующие решения"


def test_h04_fixer_disabled_in_profile_is_noop() -> None:
    """Если H.04 disabled в профиле — fix ничего не делает."""
    doc = _make_doc_with_chapters()
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["H.04"].enabled = False
    applied = run_fix(doc, profile, codes=["H.04"])
    assert applied == []


def test_h04_fixer_idempotent() -> None:
    doc = _make_doc_with_chapters()
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["H.04"].enabled = True
    run_fix(doc, profile, codes=["H.04"])
    applied2 = run_fix(doc, profile, codes=["H.04"])
    assert applied2 == []


# --- Шаблоны блоков ---


def test_block_templates_factories_produce_valid_dicts() -> None:
    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _BLOCK_TEMPLATES

    for key, (label, factory) in _BLOCK_TEMPLATES.items():
        result = factory()
        # Либо dict (один блок), либо list[dict] (несколько связанных).
        assert isinstance(result, (dict, list))
        if isinstance(result, dict):
            assert "kind" in result
        else:
            for blk in result:
                assert isinstance(blk, dict)
                assert "kind" in blk


def test_block_template_intro_has_list() -> None:
    """Шаблон 'Введение' содержит список задач."""
    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _BLOCK_TEMPLATES

    _, factory = _BLOCK_TEMPLATES["intro_block"]
    blocks = factory()
    assert isinstance(blocks, list)
    kinds = [b["kind"] for b in blocks]
    assert "list" in kinds


def test_block_template_table_3x3() -> None:
    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _BLOCK_TEMPLATES

    _, factory = _BLOCK_TEMPLATES["table_3x3_captioned"]
    block = factory()
    assert block["kind"] == "table"
    assert len(block["headers"]) == 3
    assert len(block["rows"]) == 3


def test_block_template_toc_uses_correct_kind() -> None:
    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _BLOCK_TEMPLATES

    # Проверим, что среди всех шаблонов нет ошибочного TOC-блока через
    # шаблоны разделов (только через builder-API .table_of_contents()).
    for key, (_, factory) in _BLOCK_TEMPLATES.items():
        result = factory()
        items = result if isinstance(result, list) else [result]
        for blk in items:
            if blk.get("kind") == "toc":
                # TOC обязательно имеет min_level/max_level.
                assert "min_level" in blk
                assert "max_level" in blk


# --- Live-preview TOC ---


def test_render_toc_preview_importable() -> None:
    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _render_toc_preview_panel

    assert callable(_render_toc_preview_panel)
