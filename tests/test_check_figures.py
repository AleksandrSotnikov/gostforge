"""Тесты I.01 — у каждого рисунка должна быть подпись."""

# ruff: noqa: RUF001, RUF002

from gostforge.model import (
    Document,
    Figure,
    LogicalSection,
    PageSection,
    Paragraph,
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


def test_i01_registered() -> None:
    assert "I.01" in registered_checks()


def test_i01_figure_with_caption_no_violation() -> None:
    figure = Figure(
        id="fig-1",
        image_path="",
        caption=[TextRun(text="Рисунок 1 — Схема алгоритма")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert found == []


def test_i01_figure_without_caption_violation() -> None:
    figure = Figure(id="fig-1", image_path="", caption=[])
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1
    assert found[0].details["figure_id"] == "fig-1"
    assert "fig-1" in found[0].location


def test_i01_figure_with_empty_text_caption_violation() -> None:
    """Caption из TextRun только с пробелами — тоже нарушение."""
    figure = Figure(
        id="fig-2",
        image_path="",
        caption=[TextRun(text="   ")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1


def test_i01_figures_in_logical_sections() -> None:
    """Рисунки внутри LogicalSection.children тоже проверяются."""
    fig_ok = Figure(id="fig-a", caption=[TextRun(text="Рисунок A")])
    fig_bad = Figure(id="fig-b", caption=[])
    section = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[Paragraph(id="p-1"), fig_ok, fig_bad],
    )
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1
    assert found[0].details["figure_id"] == "fig-b"


def test_i01_nested_logical_sections() -> None:
    """Рисунки во вложенных подсекциях тоже находятся."""
    fig_bad = Figure(id="fig-deep", caption=[])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[fig_bad],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1
    assert found[0].details["figure_id"] == "fig-deep"
