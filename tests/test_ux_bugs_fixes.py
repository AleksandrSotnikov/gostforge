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


def test_list_paragraph_has_explicit_left(tmp_path: Path) -> None:
    """Каждый параграф списка имеет явный <w:ind w:left=N .../>,
    переопределяющий первый отступ из стиля Normal. По ГОСТ
    7.32-2017 — left = 1.25 см (709 twips), hanging = 0 (маркер
    ровно на абзацном отступе)."""
    b = work("X", year=2026).section("Введение").list(
        ["короткий", "длинный элемент списка, который точно перенесётся"],
        ordered=False,
    )
    out = tmp_path / "list.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    list_pprs = re.findall(
        r"<w:pPr>(?:(?!</w:pPr>).)*<w:numPr>.*?</w:pPr>", doc_xml, re.DOTALL
    )
    assert list_pprs, "Параграфов списка с numPr не найдено"
    for ppr in list_pprs:
        ind_match = re.search(r"<w:ind\b[^/]*/>", ppr)
        assert ind_match, f"<w:ind> отсутствует в pPr списка: {ppr[:200]}"
        ind = ind_match.group(0)
        assert 'w:left="' in ind, f"<w:ind> без w:left: {ind}"
        # Либо hanging (если > 0), либо firstLine="0" (если hanging=0).
        # Главное — не должно быть пустого <w:ind> или firstLine > 0.
        assert (
            'w:hanging="' in ind
            or 'w:firstLine="0"' in ind
        ), f"<w:ind> без hanging И без firstLine=0: {ind}"


def test_list_marker_at_1_25cm_by_default(tmp_path: Path) -> None:
    """Default-профиль: маркер списка на позиции 1.25 см от поля
    (по ГОСТ 7.32-2017 п. 6.5 «запись с абзацного отступа»).

    Используется классический hanging-list: маркер на (left - hanging),
    текст продолжения на left. Default-значения дают:
    * left = 1.75 см = 992 twips
    * hanging = 0.5 см = 283 twips
    * маркер в позиции (left - hanging) = 1.25 см = 709 twips ✓
    * перенос строки выровнен на left = 1.75 см (под текстом
      первой строки, не под маркером)
    """
    b = work("X", year=2026).section("Введение").list(["a", "b"], ordered=False)
    out = tmp_path / "marker.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)

    numbering = _docx_xml(out, "word/numbering.xml")
    last_lvl = re.findall(
        r'<w:lvl w:ilvl="0">.*?</w:lvl>', numbering, re.DOTALL
    )[-1]
    nb_ind = re.search(r"<w:ind\b[^/]*/>", last_lvl).group(0)
    # left - hanging должно дать 709 twips (1.25 cm) — позиция маркера.
    left_match = re.search(r'w:left="(\d+)"', nb_ind)
    hanging_match = re.search(r'w:hanging="(\d+)"', nb_ind)
    assert left_match
    left_val = int(left_match.group(1))
    hanging_val = int(hanging_match.group(1)) if hanging_match else 0
    marker_position = left_val - hanging_val
    assert marker_position == 709, (
        f"Маркер не на 1.25см. left={left_val}, hanging={hanging_val}, "
        f"marker_position={marker_position}"
    )


def test_list_paragraph_overrides_normal_first_line_indent(
    tmp_path: Path,
) -> None:
    """Регрессионный guard: параграф списка должен перекрывать
    Normal-стиль (где first_line_indent=1.25см). Это или через
    hanging > 0, или через firstLine = 0."""
    b = work("X", year=2026).section("Введение").list(["a", "b"], ordered=True)
    out = tmp_path / "ord.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    list_pprs = re.findall(
        r"<w:pPr>(?:(?!</w:pPr>).)*<w:numPr>.*?</w:pPr>", doc_xml, re.DOTALL
    )
    for ppr in list_pprs:
        ind_match = re.search(r"<w:ind\b[^/]*/>", ppr)
        assert ind_match
        ind = ind_match.group(0)
        # firstLine не должен быть > 0 (это означает красную строку
        # на параграфе списка — не по ГОСТу).
        firstLine_match = re.search(r'w:firstLine="(\d+)"', ind)
        if firstLine_match:
            assert int(firstLine_match.group(1)) == 0, (
                f"firstLine > 0 в параграфе списка: {ind}"
            )