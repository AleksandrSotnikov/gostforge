"""Тесты B.01 — у каждой таблицы должна быть подпись."""

# ruff: noqa: RUF001, RUF002

from gostforge.model import (
    Document,
    LogicalSection,
    PageSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _doc_with_content(items: list[object]) -> Document:
    doc = Document()
    page_section = PageSection(
        id="main",
        name="m",
        type="main",
        content=list(items),  # type: ignore[arg-type]
    )
    doc.page_sections.append(page_section)
    return doc


def test_b01_registered() -> None:
    assert "B.01" in registered_checks()


def test_b01_table_with_caption_no_violation() -> None:
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — Результаты")],
        headers=[[TextRun(text="A")]],
        rows=[[[TextRun(text="1")]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert found == []


def test_b01_table_without_caption_violation() -> None:
    table = Table(
        id="t-1",
        caption=[],
        headers=[[TextRun(text="A")]],
        rows=[[[TextRun(text="1")]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-1"
    assert "t-1" in found[0].location


def test_b01_table_with_empty_text_caption_violation() -> None:
    """Caption из TextRun только с пробелами — тоже нарушение."""
    table = Table(id="t-2", caption=[TextRun(text=" ")])
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1


def test_b01_tables_in_logical_sections() -> None:
    """Таблицы внутри LogicalSection.children тоже проверяются."""
    table_ok = Table(
        id="t-a", caption=[TextRun(text="Таблица A")]
    )
    table_bad = Table(id="t-b", caption=[])
    section = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[Paragraph(id="p-1"), table_ok, table_bad],
    )
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-b"


def test_b01_nested_logical_sections() -> None:
    """Таблицы во вложенных подсекциях тоже находятся."""
    table_bad = Table(id="t-deep", caption=[])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[table_bad],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-deep"
