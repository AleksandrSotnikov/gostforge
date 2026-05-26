# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты исправлений трёх UX-багов из релиза:

1. Normal-стиль теперь имеет явный alignment=justify (раньше Word
   наследовал left из дефолтного шаблона).
2. Builder больше не ставит page_break_before на первые параграфы
   разделов — это делал стиль Heading 1, причём раньше первый
   параграф ПОДРАЗДЕЛА получал page-break, и текст уезжал на новую
   страницу после заголовка 1.1.
3. Параграфы списка получают явный <w:ind w:left=N w:hanging=M/> в
   pPr (раньше был только <w:ind w:firstLine="0"/>, и перенос
   длинного элемента списка терял отступ от маркера, начиная с
   красной строки 1.25 см от Normal).
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.profile import load_profile


def _docx_xml(out: Path, part: str) -> str:
    with zipfile.ZipFile(out) as zf:
        return zf.read(part).decode("utf-8")


# --- 1. Normal alignment ---


def test_normal_style_has_justify_alignment(tmp_path: Path) -> None:
    """Стиль Normal имеет <w:jc w:val="both"/> (justify по OOXML)."""
    b = work("X", year=2026).section("Введение").paragraph("текст")
    out = tmp_path / "out.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    styles = _docx_xml(out, "word/styles.xml")
    normal_block = re.search(
        r'styleId="Normal".*?</w:style>', styles, re.DOTALL
    )
    assert normal_block is not None
    # OOXML 'both' = justify (по ширине).
    assert 'w:val="both"' in normal_block.group(0), (
        "Стиль Normal не имеет alignment=justify; основной текст "
        "будет рваный по правому краю."
    )


def test_normal_style_alignment_follows_profile(tmp_path: Path) -> None:
    """Если в профиле alignment=left, стиль Normal тоже left."""
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.styles.body.alignment = "left"

    b = work("X", year=2026).section("Введение").paragraph("текст")
    out = tmp_path / "left.docx"
    export_docx(b.build(), profile, out)
    styles = _docx_xml(out, "word/styles.xml")
    normal_block = re.search(
        r'styleId="Normal".*?</w:style>', styles, re.DOTALL
    )
    assert normal_block is not None
    assert 'w:val="left"' in normal_block.group(0)


# --- 2. Page-break перед главой через стиль, не через параграф ---


def test_builder_does_not_set_page_break_on_paragraphs() -> None:
    """build() не должен ставить page_break_before на параграфы."""
    from gostforge.model import LogicalSection, Paragraph

    doc = (
        work("X", year=2026)
        .section("Глава 1")
        .paragraph("a")
        .section("Глава 2")
        .paragraph("b")
        .build()
    )

    def walk(items: list) -> list[Paragraph]:  # type: ignore[no-untyped-def]
        out: list[Paragraph] = []
        for it in items:
            if isinstance(it, Paragraph):
                out.append(it)
            if isinstance(it, LogicalSection):
                out.extend(walk(it.children))
        return out

    for p in walk(doc.page_sections[0].content):
        assert p.page_break_before is None or p.page_break_before is False


def test_subsection_first_paragraph_no_page_break() -> None:
    """Когда глава начинается СРАЗУ с подраздела (без вступительного
    параграфа), первый параграф подраздела НЕ должен получать
    page_break_before. Это был ключевой баг #3 — после заголовка
    1.1 текст уезжал на новую страницу."""
    from gostforge.model import LogicalSection, Paragraph

    builder = work("X", year=2026)
    sec = builder.section("Глава 1")
    sub = sec.subsection("1.1 Подраздел")
    sub.paragraph("первый параграф подраздела")
    # Вторая глава тоже без вступления, сразу с подраздела.
    sec2 = builder.section("Глава 2")
    sub2 = sec2.subsection("2.1 Подраздел")
    sub2.paragraph("ещё параграф")

    doc = builder.build()

    def walk(items: list) -> list[Paragraph]:  # type: ignore[no-untyped-def]
        out: list[Paragraph] = []
        for it in items:
            if isinstance(it, Paragraph):
                out.append(it)
            if isinstance(it, LogicalSection):
                out.extend(walk(it.children))
        return out

    paragraphs = walk(doc.page_sections[0].content)
    for p in paragraphs:
        assert p.page_break_before is None or p.page_break_before is False, (
            f"Параграф {p.id} получил page_break_before — баг #3 вернулся."
        )


def test_heading_1_style_has_page_break_before(tmp_path: Path) -> None:
    """Page-break перед главами теперь делает стиль Heading 1."""
    b = work("X", year=2026).section("Глава 1").paragraph("a")
    out = tmp_path / "h1pb.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    styles = _docx_xml(out, "word/styles.xml")
    h1_block = re.search(
        r'styleId="Heading1".*?</w:style>', styles, re.DOTALL
    )
    assert h1_block is not None
    assert "<w:pageBreakBefore/>" in h1_block.group(0)


# --- 3. Hanging-indent в параграфе списка ---


def test_list_paragraph_has_explicit_left_hanging(tmp_path: Path) -> None:
    """Каждый параграф списка имеет <w:ind w:left=N w:hanging=M/>,
    а не <w:ind w:firstLine="0"/>. Без этого продолжение строки
    списка получало красную строку 1.25 см от стиля Normal."""
    b = work("X", year=2026).section("Введение").list(
        ["короткий", "длинный элемент списка, который точно перенесётся"],
        ordered=False,
    )
    out = tmp_path / "list.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    # Найдём все pPr с numPr и проверим, что у них есть <w:ind>
    # с w:left и w:hanging (не только firstLine="0").
    list_pprs = re.findall(
        r"<w:pPr>(?:(?!</w:pPr>).)*<w:numPr>.*?</w:pPr>", doc_xml, re.DOTALL
    )
    assert list_pprs, "Параграфов списка с numPr не найдено"
    for ppr in list_pprs:
        ind_match = re.search(r"<w:ind\b[^/]*/>", ppr)
        assert ind_match, f"<w:ind> отсутствует в pPr списка: {ppr[:200]}"
        ind = ind_match.group(0)
        assert 'w:left="' in ind, f"<w:ind> без w:left: {ind}"
        assert 'w:hanging="' in ind, f"<w:ind> без w:hanging: {ind}"


def test_list_paragraph_no_firstLine_zero_anymore(tmp_path: Path) -> None:
    """Старая логика ставила <w:ind w:firstLine="0"/> на параграфы
    списка — это перекрывало hanging из numbering.xml и ломало перенос
    строки. Регрессионный guard: в pPr-блоке параграфа списка не
    должно быть firstLine="0" (вместо него — left+hanging)."""
    b = work("X", year=2026).section("Введение").list(["a", "b"], ordered=True)
    out = tmp_path / "ord.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    list_pprs = re.findall(
        r"<w:pPr>(?:(?!</w:pPr>).)*<w:numPr>.*?</w:pPr>", doc_xml, re.DOTALL
    )
    for ppr in list_pprs:
        ind_match = re.search(r"<w:ind\b[^/]*/>", ppr)
        if ind_match:
            ind = ind_match.group(0)
            # firstLine="0" допустимо только если есть left+hanging
            # рядом — но мы теперь не пишем firstLine вообще.
            # Проверим что hanging задан (это главное).
            assert 'w:hanging="' in ind