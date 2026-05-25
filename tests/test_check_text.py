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


# --- T.03 (межстрочный интервал) -------------------------------------------


def test_t03_correct_line_spacing_no_violation() -> None:
    paragraph = Paragraph(
        id="p1", content=[TextRun(text="Текст")], style_name="Normal", line_spacing=1.5
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.03"]
    assert found == []


def test_t03_wrong_line_spacing_violation() -> None:
    paragraph = Paragraph(
        id="p1", content=[TextRun(text="Текст")], style_name="Normal", line_spacing=1.0
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.03"]
    assert len(found) == 1
    assert found[0].details["expected"] == "1.5"


def test_t03_skips_paragraph_without_explicit_spacing() -> None:
    """line_spacing=None означает «наследуется от стиля» — не нарушение."""
    paragraph = Paragraph(id="p1", content=[TextRun(text="Текст")], style_name="Normal")
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.03"]
    assert found == []


def test_t03_ignores_captions() -> None:
    """У подписей рисунков/таблиц своя строка — не считается нарушением T.03."""
    paragraph = Paragraph(
        id="p1", content=[TextRun(text="Рисунок 1")], style_name="Caption", line_spacing=1.0
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.03"]
    assert found == []


# --- T.04 (отступ красной строки) ------------------------------------------


def test_t04_correct_indent_no_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст")],
        style_name="Normal",
        first_line_indent_cm=1.25,
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.04"]
    assert found == []


def test_t04_wrong_indent_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст")],
        style_name="Normal",
        first_line_indent_cm=0.5,
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.04"]
    assert len(found) == 1


def test_t04_indent_within_tolerance() -> None:
    """1.26 см — в пределах допуска 0.05 см."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст")],
        style_name="Normal",
        first_line_indent_cm=1.26,
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.04"]
    assert found == []


# --- T.05 (выравнивание) ---------------------------------------------------


def test_t05_correct_alignment_no_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст")],
        style_name="Normal",
        alignment="justify",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.05"]
    assert found == []


def test_t05_wrong_alignment_violation() -> None:
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Текст")],
        style_name="Normal",
        alignment="left",
    )
    doc = _doc_with_paragraph(paragraph)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.05"]
    assert len(found) == 1
    assert found[0].details["actual"] == "left"


def test_t05_skips_headings_and_captions() -> None:
    """Заголовки и подписи имеют собственное выравнивание (H.*/I.*/B.*)."""
    heading = Paragraph(
        id="p1",
        content=[TextRun(text="Введение")],
        style_name="Heading 1",
        alignment="center",
    )
    caption = Paragraph(
        id="p2",
        content=[TextRun(text="Рисунок 1")],
        style_name="Caption",
        alignment="center",
    )
    doc = Document()
    doc.page_sections.append(
        PageSection(id="main", name="m", type="main", content=[heading, caption])
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.05"]
    assert found == []


# --- T.07 (нет пустых абзацев подряд) --------------------------------------


def _empty_para(pid: str) -> Paragraph:
    return Paragraph(id=pid, content=[TextRun(text="")], style_name="Normal")


def _text_para(pid: str, text: str = "Текст") -> Paragraph:
    return Paragraph(id=pid, content=[TextRun(text=text)], style_name="Normal")


def test_t07_registered() -> None:
    assert "T.07" in registered_checks()


def test_t07_single_empty_paragraph_no_violation() -> None:
    """Один пустой абзац подряд — допустимо (max_consecutive_empty=1)."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[_text_para("p1"), _empty_para("p2"), _text_para("p3")],
        )
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.07"]
    assert found == []


def test_t07_two_empty_paragraphs_violation() -> None:
    """Два пустых абзаца подряд — нарушение."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[
                _text_para("p1"),
                _empty_para("p2"),
                _empty_para("p3"),
                _text_para("p4"),
            ],
        )
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.07"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["count"] == "2"


def test_t07_three_empty_paragraphs_at_end_violation() -> None:
    """Цепочка пустых абзацев в конце контейнера тоже должна детектиться."""
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[
                _text_para("p1"),
                _empty_para("p2"),
                _empty_para("p3"),
                _empty_para("p4"),
            ],
        )
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.07"]
    assert len(found) == 1
    assert found[0].details["count"] == "3"


def test_t07_chain_resets_across_logical_section_boundary() -> None:
    """Пустой абзац в конце одного раздела и в начале следующего — не цепочка."""
    sec_a = LogicalSection(
        id="a", level=1, children=[_text_para("a1"), _empty_para("a2")]
    )
    sec_b = LogicalSection(
        id="b", level=1, children=[_empty_para("b1"), _text_para("b2")]
    )
    doc = Document()
    doc.page_sections.append(
        PageSection(id="main", name="m", type="main", content=[sec_a, sec_b])
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "T.07"]
    assert found == []


def test_t07_custom_limit_via_profile_params() -> None:
    """max_consecutive_empty=2 — два пустых ОК, три — нарушение."""
    profile = load_profile("gost-7.32-2017")
    profile.checks["T.07"].params["max_consecutive_empty"] = 2
    ok_doc = Document()
    ok_doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[
                _text_para("p1"),
                _empty_para("p2"),
                _empty_para("p3"),
                _text_para("p4"),
            ],
        )
    )
    assert [v for v in validate(ok_doc, profile) if v.check_code == "T.07"] == []

    bad_doc = Document()
    bad_doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[
                _text_para("p1"),
                _empty_para("p2"),
                _empty_para("p3"),
                _empty_para("p4"),
                _text_para("p5"),
            ],
        )
    )
    bad = [v for v in validate(bad_doc, profile) if v.check_code == "T.07"]
    assert len(bad) == 1
    assert bad[0].details["count"] == "3"
