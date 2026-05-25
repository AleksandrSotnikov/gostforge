"""Тесты парсера .docx → Document."""

# ruff: noqa: RUF001, RUF002

from __future__ import annotations

from pathlib import Path

from gostforge.model import LogicalSection, Paragraph, TextRun
from gostforge.parser.docx_parser import parse_docx

from .conftest import make_docx


def test_parse_extracts_metadata(tmp_path: Path) -> None:
    """Title из docProps попадает в Document.metadata.title."""
    path = make_docx(
        tmp_path / "with_title.docx",
        paragraphs=["Один абзац"],
        title="Моя курсовая работа",
        author="Студент",
    )
    doc = parse_docx(path)
    assert doc.metadata.title == "Моя курсовая работа"
    assert doc.metadata.author == "Студент"
    # year проставляется из core.created — это либо None, либо валидный
    # четырёхзначный год (python-docx по умолчанию ставит 2013).
    assert doc.metadata.year is None or doc.metadata.year >= 2000


def test_parse_extracts_margins(tmp_path: Path) -> None:
    """Поля страницы в мм извлекаются корректно."""
    path = make_docx(
        tmp_path / "margins.docx",
        margins_mm={"top": 20, "right": 15, "bottom": 20, "left": 30},
        paragraphs=["Текст"],
    )
    doc = parse_docx(path)
    assert len(doc.page_sections) == 1
    margins = doc.page_sections[0].page.margins_mm
    assert margins["top"] == 20.0
    assert margins["right"] == 15.0
    assert margins["bottom"] == 20.0
    assert margins["left"] == 30.0


def test_parse_extracts_font_and_size(tmp_path: Path) -> None:
    """Шрифт и кегль из стиля Normal видны в content рунов."""
    path = make_docx(
        tmp_path / "font.docx",
        body_font="Times New Roman",
        body_size=14,
        paragraphs=["Тестовый абзац для проверки шрифта"],
    )
    doc = parse_docx(path)
    runs: list[TextRun] = []
    for item in doc.page_sections[0].content:
        if isinstance(item, Paragraph):
            for elem in item.content:
                if isinstance(elem, TextRun):
                    runs.append(elem)
    assert any(r.font == "Times New Roman" and r.size_pt == 14.0 for r in runs), (
        f"Не найден run с TNR/14, runs={[(r.font, r.size_pt) for r in runs]}"
    )


def test_parse_extracts_headings(tmp_path: Path) -> None:
    """Каждый Heading становится LogicalSection с соответствующим текстом."""
    path = make_docx(
        tmp_path / "headings.docx",
        headings=[(1, "Введение"), (1, "Заключение")],
        paragraphs=[],
    )
    doc = parse_docx(path)
    sections = [item for item in doc.page_sections[0].content if isinstance(item, LogicalSection)]
    assert len(sections) == 2

    def heading_text(s: LogicalSection) -> str:
        return "".join(e.text for e in s.heading if isinstance(e, TextRun))

    titles = [heading_text(s) for s in sections]
    assert "Введение" in titles
    assert "Заключение" in titles
    assert all(s.level == 1 for s in sections)


def test_parse_detects_page_number_field(tmp_path: Path) -> None:
    """page_number=True → footer.default.center содержит TextRun('{page}')."""
    path_with = make_docx(
        tmp_path / "with_page.docx",
        paragraphs=["Хоть какой-то текст"],
        page_number=True,
    )
    doc_with = parse_docx(path_with)
    footer = doc_with.page_sections[0].footer
    assert footer is not None, "Footer должен быть распознан"
    center = footer.default.center
    assert center is not None
    assert any(isinstance(e, TextRun) and e.text == "{page}" for e in center)
    assert doc_with.page_sections[0].page_numbering.visible is True


def test_parse_no_page_number_field(tmp_path: Path) -> None:
    """page_number=False → footer не содержит маркера {page}."""
    path_without = make_docx(
        tmp_path / "no_page.docx",
        paragraphs=["Текст без номера"],
        page_number=False,
    )
    doc_without = parse_docx(path_without)
    footer = doc_without.page_sections[0].footer
    if footer is not None:
        center = footer.default.center or []
        assert not any(isinstance(e, TextRun) and e.text == "{page}" for e in center)


def test_parse_paragraph_after_heading_goes_into_children(tmp_path: Path) -> None:
    """Абзацы после заголовка кладутся в children соответствующей LogicalSection."""
    path = make_docx(
        tmp_path / "structure.docx",
        headings=[(1, "Введение")],
        paragraphs=["Первый абзац введения."],
    )
    doc = parse_docx(path)
    content = doc.page_sections[0].content
    sections = [c for c in content if isinstance(c, LogicalSection)]
    assert len(sections) == 1
    # Один параграф должен попасть внутрь раздела.
    children = sections[0].children
    paragraphs_inside = [c for c in children if isinstance(c, Paragraph)]
    assert len(paragraphs_inside) == 1
    text = "".join(e.text for e in paragraphs_inside[0].content if isinstance(e, TextRun))
    assert "Первый абзац" in text
