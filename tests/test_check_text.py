"""Тесты T.01 (шрифт) и T.02 (кегль)."""

from gostforge.model import (
    Document,
    LogicalSection,
    PageGeometry,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _doc_with_paragraph(paragraph: Paragraph) -> Document:
    """Утилита: документ с одной страничной секцией и одним абзацем."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=PageGeometry(),
            content=[paragraph],
        )
    )
    return doc


# --- T.01 -------------------------------------------------------------------


def test_t01_registered() -> None:
    assert "T.01" in registered_checks()


def test_t01_correct_font_no_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст", font="Times New Roman", size_pt=14)],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.01"]
    assert found == []


def test_t01_wrong_font_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст", font="Arial", size_pt=14)],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.01"]
    assert len(found) == 1
    assert found[0].severity == "error"
    assert "Arial" in found[0].message
    assert found[0].details["expected"] == "Times New Roman"


def test_t01_skips_runs_without_font() -> None:
    """Если у run шрифт не задан явно (наследует от стиля) — это не нарушение."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст", font=None, size_pt=None)],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.01"]
    assert found == []


def test_t01_skips_headers_and_footers() -> None:
    """Колонтитулы проверяются отдельной категорией K.*, не T.01."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Header", font="Calibri", size_pt=11)],
        style_name="Header",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.01"]
    assert found == []


def test_t01_recurses_into_logical_sections() -> None:
    """T.01 должна обходить вложенные LogicalSection."""
    wrong_para = Paragraph(
        id="p1",
        content=[TextRun(text="Глава", font="Arial", size_pt=14)],
        style_name="Normal",
    )
    section = LogicalSection(id="s1", level=1, children=[wrong_para])
    doc = Document()
    doc.page_sections.append(
        PageSection(id="main", name="m", type="main", content=[section])
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.01"]
    assert len(found) == 1


# --- T.02 -------------------------------------------------------------------


def test_t02_registered() -> None:
    assert "T.02" in registered_checks()


def test_t02_correct_body_size_no_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст", font="Times New Roman", size_pt=14)],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.02"]
    assert found == []


def test_t02_wrong_body_size_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст", font="Times New Roman", size_pt=12)],
        style_name="Normal",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.02"]
    assert len(found) == 1
    assert found[0].details["expected"] == "14.0"
    assert found[0].details["actual"] == "12"
    assert found[0].details["category"] == "body"


def test_t02_caption_uses_caption_size() -> None:
    """Caption-абзац с кеглем 12 — допустимо (caption_size_pt = 12 по умолчанию)."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Рисунок 1 — схема", font="Times New Roman", size_pt=12)],
        style_name="Caption",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.02"]
    assert found == []


def test_t02_caption_wrong_size_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Рисунок 1", font="Times New Roman", size_pt=14)],
        style_name="Caption",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.02"]
    assert len(found) == 1
    assert found[0].details["category"] == "caption"
