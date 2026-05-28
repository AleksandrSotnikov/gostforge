"""Тесты T.14 — проверка интервалов между абзацами основного текста."""

from __future__ import annotations

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
from gostforge.validator import validate


def _make_doc(paragraphs: list[Paragraph]) -> Document:
    doc = Document(metadata=DocumentMetadata(title="X"))
    section = LogicalSection(
        id="sec-1",
        heading=[TextRun(text="Введение")],
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


def test_t14_no_violation_when_spacing_zero() -> None:
    """Идеальный случай: space_before/after = 0 → нет нарушений."""
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=0,
        space_after_pt=0,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert violations == []


def test_t14_detects_excess_before() -> None:
    """space_before_pt=10 при ожидаемом 0 → T.14."""
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=10,
        space_after_pt=0,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert len(violations) == 1
    assert "10" in violations[0].message
    assert "перед" in violations[0].message.lower()


def test_t14_detects_excess_after() -> None:
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=0,
        space_after_pt=10,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert len(violations) == 1
    assert "после" in violations[0].message.lower()


def test_t14_ignores_heading_paragraphs() -> None:
    """Heading-style параграфы пропускаются — у них свой spacing через H.07."""
    p = Paragraph(
        id="p1",
        style_name="Heading 1",
        space_before_pt=18,
        space_after_pt=12,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert violations == []


def test_t14_ignores_caption_paragraphs() -> None:
    p = Paragraph(
        id="p1",
        style_name="Caption",
        space_before_pt=20,
        space_after_pt=20,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert violations == []


def test_t14_respects_tolerance() -> None:
    """Допуск 0.5 pt — небольшое отклонение из-за округлений не нарушение."""
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=0.3,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert violations == []


def test_t14_uses_profile_expected_value() -> None:
    """Профиль может ожидать ненулевое значение (кафедральная методичка)."""
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.styles.body.space_after_pt = 6
    # Параграф с 6 pt — норма, с 10 — нарушение.
    p1 = Paragraph(
        id="p1",
        style_name="Normal",
        space_after_pt=6,
        content=[TextRun(text="x")],
    )
    p2 = Paragraph(
        id="p2",
        style_name="Normal",
        space_after_pt=10,
        content=[TextRun(text="y")],
    )
    doc = _make_doc([p1, p2])
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert len(violations) == 1
    assert violations[0].location.endswith("p2.space_after_pt")


def test_t14_skips_unset_values() -> None:
    """space_*=None означает «не задано явно» — пропускаем."""
    p = Paragraph(
        id="p1",
        style_name="Normal",
        space_before_pt=None,
        space_after_pt=None,
        content=[TextRun(text="x")],
    )
    doc = _make_doc([p])
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "T.14"]
    assert violations == []
