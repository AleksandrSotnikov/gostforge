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
    doc.page_sections.append(
        PageSection(id="main", name="m", type="main", content=list(items))
    )
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
