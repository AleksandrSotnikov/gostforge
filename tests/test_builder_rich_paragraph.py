"""Тесты SectionBuilder.rich_paragraph (Фаза 2.5).

Покрытие: смешанный контент абзаца — TextRun + CrossRef + InlineFormula
+ Citation, преемственность .paragraph() поверх .rich_paragraph(),
fluent-цепочка.
"""

from __future__ import annotations

from gostforge.builder import work
from gostforge.model import (
    Citation,
    CrossRef,
    Document,
    InlineFormula,
    LogicalSection,
    Paragraph,
    TextRun,
)


def _first_paragraph(doc: Document) -> Paragraph:
    """Достать первый Paragraph из первого LogicalSection документа."""
    for ps in doc.page_sections:
        for child in ps.content:
            if isinstance(child, LogicalSection):
                for inner in child.children:
                    if isinstance(inner, Paragraph):
                        return inner
    raise AssertionError("в документе нет ни одного Paragraph")


def test_rich_paragraph_keeps_inline_elements_order() -> None:
    """rich_paragraph сохраняет порядок и типы inline-элементов."""
    doc = (
        work("T")
        .section("Введение")
        .rich_paragraph(
            [
                TextRun(text="Энергия "),
                InlineFormula(latex=r"E = h\nu"),
                TextRun(text=" описана в "),
                Citation(source_id="planck-1900", pages="42"),
                TextRun(text="."),
            ]
        )
        .build()
    )
    para = _first_paragraph(doc)
    kinds = [type(el).__name__ for el in para.content]
    assert kinds == ["TextRun", "InlineFormula", "TextRun", "Citation", "TextRun"]


def test_rich_paragraph_supports_cross_ref_with_prefix() -> None:
    """CrossRef.prefix передаётся без потерь."""
    doc = (
        work("T")
        .section("Глава 1")
        .rich_paragraph(
            [
                TextRun(text="Подробнее"),
                CrossRef(target_id="fig-1", prefix=" (см. "),
                TextRun(text=")."),
            ]
        )
        .build()
    )
    para = _first_paragraph(doc)
    xref = para.content[1]
    assert isinstance(xref, CrossRef)
    assert xref.target_id == "fig-1"
    assert xref.prefix == " (см. "


def test_paragraph_delegates_to_rich_paragraph() -> None:
    """.paragraph(text) остаётся обёрткой над .rich_paragraph и работает как раньше."""
    doc = work("T").section("Введение").paragraph("Простой текст", bold=True).build()
    para = _first_paragraph(doc)
    assert len(para.content) == 1
    run = para.content[0]
    assert isinstance(run, TextRun)
    assert run.text == "Простой текст"
    assert run.bold is True


def test_rich_paragraph_returns_self_for_chaining() -> None:
    """Fluent: .rich_paragraph(...).paragraph(...).rich_paragraph(...) — цепочка."""
    builder = (
        work("T")
        .section("Введение")
        .rich_paragraph([TextRun(text="Один")])
        .paragraph("Два")
        .rich_paragraph([TextRun(text="Три")])
    )
    doc = builder.build()
    # Считаем количество параграфов в первом логическом разделе.
    section: LogicalSection | None = None
    for ps in doc.page_sections:
        for child in ps.content:
            if isinstance(child, LogicalSection):
                section = child
                break
    assert section is not None
    paragraphs = [c for c in section.children if isinstance(c, Paragraph)]
    assert len(paragraphs) == 3
    texts = ["".join(el.text for el in p.content if isinstance(el, TextRun)) for p in paragraphs]
    assert texts == ["Один", "Два", "Три"]


def test_rich_paragraph_accepts_empty_list() -> None:
    """Пустой список валиден — параграф будет пустым."""
    doc = work("T").section("Введение").rich_paragraph([]).build()
    para = _first_paragraph(doc)
    assert para.content == []


def test_rich_paragraph_does_not_mutate_input() -> None:
    """rich_paragraph не должен сохранять ссылку на переданный список.

    Если вызывающий код позже мутирует свой список, это не должно
    отразиться на содержимом параграфа в модели.
    """
    elements = [TextRun(text="изначальный")]
    doc = work("T").section("Введение").rich_paragraph(elements).build()
    elements.append(TextRun(text="лишний"))  # мутация после билда
    para = _first_paragraph(doc)
    assert len(para.content) == 1
    first = para.content[0]
    assert isinstance(first, TextRun)
    assert first.text == "изначальный"
