"""Тесты gostforge.stats.compute_stats."""

from gostforge.model import (
    BibliographyEntry,
    Document,
    Figure,
    LogicalSection,
    PageSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.stats import compute_stats


def _doc_with_content(items: list[object]) -> Document:
    doc = Document()
    doc.page_sections.append(PageSection(id="main", name="m", type="main", content=list(items)))
    return doc


def test_compute_stats_empty_document() -> None:
    doc = Document()
    s = compute_stats(doc)
    assert s.page_sections == 0
    assert s.paragraphs == 0
    assert s.tables == 0
    assert s.figures == 0
    assert s.bibliography_entries == 0


def test_compute_stats_counts_basic_blocks() -> None:
    doc = _doc_with_content(
        [
            Paragraph(id="p1", content=[TextRun(text="Привет мир")]),
            Paragraph(id="p2", content=[TextRun(text="")]),  # пустой
            Table(id="t1"),
            Figure(id="fig-1"),
        ]
    )
    s = compute_stats(doc)
    assert s.page_sections == 1
    assert s.paragraphs == 2
    assert s.paragraphs_non_empty == 1
    assert s.tables == 1
    assert s.figures == 1
    assert s.words == 2  # «Привет мир» = 2 слова
    assert s.characters == len("Привет мир")


def test_compute_stats_recurses_into_logical_sections() -> None:
    """Вложенные LogicalSection учитываются и для уровней, и для содержимого."""
    level_2 = LogicalSection(
        id="s2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[Paragraph(id="p", content=[TextRun(text="Один два три")])],
    )
    level_1 = LogicalSection(
        id="s1",
        level=1,
        heading=[TextRun(text="Глава")],
        children=[level_2, Table(id="t1")],
    )
    doc = _doc_with_content([level_1])
    s = compute_stats(doc)
    assert s.logical_sections_level_1 == 1
    assert s.logical_sections_total == 2  # level 1 + level 2
    assert s.paragraphs == 1
    assert s.words == 3
    assert s.tables == 1


def test_compute_stats_counts_bibliography() -> None:
    doc = Document()
    doc.bibliography.extend(
        [
            BibliographyEntry(id="r1", type="book", fields={"raw": "Иванов 2020"}),
            BibliographyEntry(id="r2", type="web", fields={"raw": "https://x.ru 2024"}),
        ]
    )
    s = compute_stats(doc)
    assert s.bibliography_entries == 2


def test_compute_stats_counts_subsection_levels() -> None:
    """level=2 и level=3 учитываются отдельно от total."""
    level_3 = LogicalSection(id="s3", level=3, heading=[TextRun(text="1.1.1")])
    level_2 = LogicalSection(id="s2", level=2, heading=[TextRun(text="1.1")], children=[level_3])
    level_1 = LogicalSection(id="s1", level=1, heading=[TextRun(text="1")], children=[level_2])
    doc = _doc_with_content([level_1])
    s = compute_stats(doc)
    assert s.logical_sections_level_1 == 1
    assert s.logical_sections_level_2 == 1
    assert s.logical_sections_level_3 == 1
    assert s.logical_sections_total == 3


def test_compute_stats_counts_lists_and_formulas() -> None:
    """ListBlock + Formula считаются."""
    from gostforge.model import Formula, ListBlock

    doc = _doc_with_content(
        [
            ListBlock(id="l1", items=[[TextRun(text="первый")], [TextRun(text="второй")]]),
            ListBlock(id="l2", items=[[TextRun(text="один")]]),
            Formula(id="f1", latex="E = mc^2"),
        ]
    )
    s = compute_stats(doc)
    assert s.lists == 2
    assert s.list_items == 3
    assert s.formulas == 1


def test_compute_stats_counts_paragraphs_with_inline_elements() -> None:
    """Параграфы с InlineFormula / CrossRef / Citation считаются отдельно."""
    from gostforge.model import Citation, CrossRef, InlineFormula

    p_formula = Paragraph(
        id="p1",
        content=[TextRun(text="См. "), InlineFormula(latex="x^2")],
    )
    p_xref = Paragraph(
        id="p2",
        content=[TextRun(text="См. рисунок "), CrossRef(target_id="fig-1")],
    )
    p_cite = Paragraph(
        id="p3",
        content=[TextRun(text="как пишет "), Citation(source_id="r1")],
    )
    p_plain = Paragraph(id="p4", content=[TextRun(text="обычный")])
    doc = _doc_with_content([p_formula, p_xref, p_cite, p_plain])
    s = compute_stats(doc)
    assert s.paragraphs_with_inline_formula == 1
    assert s.paragraphs_with_xref == 1
    assert s.paragraphs_with_citation == 1


def test_compute_stats_bibliography_by_type() -> None:
    """Распределение источников по типам."""
    doc = Document()
    doc.bibliography.extend(
        [
            BibliographyEntry(id="r1", type="book", fields={"raw": "x"}),
            BibliographyEntry(id="r2", type="book", fields={"raw": "y"}),
            BibliographyEntry(id="r3", type="article", fields={"raw": "z"}),
            BibliographyEntry(id="r4", type="web", fields={"raw": "w"}),
        ]
    )
    s = compute_stats(doc)
    assert s.bibliography_by_type == {"book": 2, "article": 1, "web": 1}


def test_avg_words_per_paragraph() -> None:
    """`avg_words_per_paragraph` корректно считается, пустые параграфы исключены."""
    doc = _doc_with_content(
        [
            Paragraph(id="p1", content=[TextRun(text="один два три")]),  # 3 слова
            Paragraph(id="p2", content=[TextRun(text="четыре пять")]),  # 2 слова
            Paragraph(id="p3", content=[TextRun(text="")]),  # пустой — игнор
        ]
    )
    s = compute_stats(doc)
    assert s.paragraphs_non_empty == 2
    assert s.words == 5
    assert s.avg_words_per_paragraph == 2.5


def test_avg_words_per_paragraph_zero_when_no_paragraphs() -> None:
    """Без непустых параграфов — 0.0, не ZeroDivisionError."""
    doc = Document()
    s = compute_stats(doc)
    assert s.avg_words_per_paragraph == 0.0
