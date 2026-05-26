"""Тесты расширенной модели inline-элементов (Фаза 2.5).

Покрытие: InlineFormula, Citation, CrossRef.prefix, TextRun.underline,
TextRun.color_hex, тип-алиас InlineElement, использование в Paragraph.
"""

from __future__ import annotations

from gostforge.model import (
    SCHEMA_VERSION,
    BlockType,
    Citation,
    CrossRef,
    InlineFormula,
    Paragraph,
    TextRun,
)


def test_schema_version_bumped_for_phase_25() -> None:
    """SCHEMA_VERSION = 0.3.0 после расширения inline-элементов."""
    assert SCHEMA_VERSION == "0.3.0"


def test_text_run_underline_default_none() -> None:
    """underline новое поле, default None (не задано)."""
    run = TextRun(text="пример")
    assert run.underline is None
    assert run.color_hex is None


def test_text_run_full_inline_formatting() -> None:
    """TextRun принимает весь набор inline-атрибутов."""
    run = TextRun(
        text="x",
        bold=True,
        italic=True,
        underline=True,
        superscript=False,
        subscript=False,
        font="Times New Roman",
        size_pt=14.0,
        color_hex="#FF0000",
    )
    assert run.bold is True
    assert run.underline is True
    assert run.color_hex == "#FF0000"


def test_cross_ref_prefix_optional() -> None:
    """CrossRef.prefix позволяет писать «(см. рисунок 3)» вместо «рисунок 3»."""
    ref_with_prefix = CrossRef(target_id="fig-1", prefix=" (см. ")
    ref_bare = CrossRef(target_id="fig-2")
    assert ref_with_prefix.prefix == " (см. "
    assert ref_bare.prefix is None
    assert ref_bare.display_template == "{kind} {num}"


def test_inline_formula_basic() -> None:
    """InlineFormula несёт latex и опциональный id."""
    f = InlineFormula(latex=r"h\nu")
    assert f.latex == r"h\nu"
    assert f.id is None


def test_citation_default_template() -> None:
    """Citation по умолчанию рендерится как [n]; pages опциональны."""
    c = Citation(source_id="ivanov-2023")
    assert c.template == "[{n}]"
    assert c.pages is None


def test_citation_with_pages() -> None:
    """Citation с pages — формат «[n, с. P]»."""
    c = Citation(source_id="ivanov-2023", pages="12-15", template="[{n}, с. {pages}]")
    assert c.pages == "12-15"
    assert c.template == "[{n}, с. {pages}]"


def test_paragraph_accepts_mixed_inline_elements() -> None:
    """Paragraph.content принимает 4 типа inline-элементов в произвольном порядке."""
    paragraph = Paragraph(
        id="p1",
        content=[
            TextRun(text="Энергия фотона "),
            InlineFormula(latex="E = h\\nu"),
            TextRun(text=" описана в "),
            Citation(source_id="planck-1900", pages="42"),
            TextRun(text=" (см. "),
            CrossRef(target_id="fig-1", prefix=""),
            TextRun(text=")."),
        ],
    )
    assert paragraph.type is BlockType.PARAGRAPH
    assert len(paragraph.content) == 7
    # Тип-нарративные проверки: union-типы корректно сосуществуют.
    kinds = [type(e).__name__ for e in paragraph.content]
    assert kinds == [
        "TextRun",
        "InlineFormula",
        "TextRun",
        "Citation",
        "TextRun",
        "CrossRef",
        "TextRun",
    ]
