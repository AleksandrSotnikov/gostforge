# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты автофиксера T.14 — приведение интервалов между абзацами к норме."""

from __future__ import annotations

from gostforge.fixer.engine import fix as run_fix
from gostforge.model import (
    Document,
    DocumentMetadata,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import load_profile


def _make_doc(paragraphs: list[Paragraph]) -> Document:
    doc = Document(metadata=DocumentMetadata(title="X"))
    section = LogicalSection(
        id="sec-1",
        heading=[TextRun(text="X")],
        level=1,
        children=list(paragraphs),
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[section],
        )
    )
    return doc


def test_t14_fixer_resets_before_to_zero() -> None:
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=10,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.14"])
    assert len(applied) == 1
    assert p.space_before_pt == 0


def test_t14_fixer_resets_after_to_zero() -> None:
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_after_pt=12,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.14"])
    assert len(applied) == 1
    assert p.space_after_pt == 0


def test_t14_fixer_handles_both_directions() -> None:
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=6,
        space_after_pt=10,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.14"])
    assert len(applied) == 2  # before и after — два fix-а
    assert p.space_before_pt == 0
    assert p.space_after_pt == 0


def test_t14_fixer_skips_headings() -> None:
    p = Paragraph(
        id="p1",
        style_name="Heading 1",
        space_before_pt=20,
        space_after_pt=20,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    applied = run_fix(doc, profile, codes=["T.14"])
    assert applied == []
    assert p.space_before_pt == 20  # heading не тронут


def test_t14_fixer_respects_profile_expected() -> None:
    """Если профиль ожидает 6 pt — fixer ставит 6, не 0."""
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.styles.body.space_after_pt = 6

    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_after_pt=12,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    applied = run_fix(doc, profile, codes=["T.14"])
    assert len(applied) == 1
    assert p.space_after_pt == 6


def test_t14_fixer_idempotent() -> None:
    """Повторный вызов на уже исправленном — 0 фиксов."""
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=10,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    run_fix(doc, profile, codes=["T.14"])
    applied2 = run_fix(doc, profile, codes=["T.14"])
    assert applied2 == []
