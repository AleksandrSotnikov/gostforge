"""Экспорт модели документа в .docx с применением стилей профиля.

Минимальная реализация Фазы 0:
- Поля страницы из профиля
- Стиль Normal (шрифт, кегль, межстрочный интервал, отступ первой строки)
- Параграфы со склейкой TextRun-ов и сохранением bold/italic/superscript/subscript
- Логические разделы как заголовки соответствующего уровня

Дальнейшие фазы (sectPr, header/footer-part, поля PAGE/STYLEREF, таблицы,
рисунки, формулы) — отдельные итерации.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import docx  # type: ignore[import-not-found]
from docx.document import Document as DocxDocument  # type: ignore[import-not-found]
from docx.shared import Cm, Mm, Pt  # type: ignore[import-not-found]
from docx.text.paragraph import Paragraph as DocxParagraph  # type: ignore[import-not-found]

from gostforge.model import (
    Block,
    Document,
    InlineElement,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile


def _apply_page_geometry(doc: DocxDocument, profile: Profile) -> None:
    """Применить поля страницы из профиля к первой секции docx."""
    margins = profile.styles.page.margins_mm
    section = doc.sections[0]
    if "top" in margins:
        section.top_margin = Mm(margins["top"])
    if "right" in margins:
        section.right_margin = Mm(margins["right"])
    if "bottom" in margins:
        section.bottom_margin = Mm(margins["bottom"])
    if "left" in margins:
        section.left_margin = Mm(margins["left"])


def _apply_normal_style(doc: DocxDocument, profile: Profile) -> None:
    """Применить шрифт/кегль/интервалы к стилю Normal."""
    body = profile.styles.body
    normal = doc.styles["Normal"]
    normal.font.name = body.font
    normal.font.size = Pt(body.size_pt)
    # Интервалы и отступы — на уровне paragraph_format стиля Normal
    pf = normal.paragraph_format
    pf.line_spacing = body.line_spacing
    pf.first_line_indent = Cm(body.first_line_indent_cm)


def _write_runs(docx_paragraph: DocxParagraph, content: Sequence[InlineElement]) -> None:
    """Записать список InlineElement как набор run-ов в docx-параграф."""
    for element in content:
        if isinstance(element, TextRun):
            run = docx_paragraph.add_run(element.text)
            if element.bold:
                run.bold = True
            if element.italic:
                run.italic = True
            if element.superscript:
                run.font.superscript = True
            if element.subscript:
                run.font.subscript = True
            if element.font:
                run.font.name = element.font
            if element.size_pt is not None:
                run.font.size = Pt(element.size_pt)
        # CrossRef в Фазе 0 не экспортируется — пропускаем


def _write_paragraph(doc: DocxDocument, paragraph: Paragraph) -> None:
    """Добавить один Paragraph в docx-документ."""
    style_name = paragraph.style_name or "Normal"
    try:
        docx_para = doc.add_paragraph(style=style_name)
    except KeyError:
        # Неизвестный стиль (например, кастомное имя) — используем Normal.
        docx_para = doc.add_paragraph(style="Normal")
    _write_runs(docx_para, paragraph.content)


def _write_logical_section(doc: DocxDocument, section: LogicalSection) -> None:
    """Добавить заголовок логического раздела и рекурсивно записать его содержимое."""
    heading_text = "".join(
        el.text for el in section.heading if isinstance(el, TextRun)
    )
    level = max(0, min(section.level, 4))  # docx supports 0..9, мы — 1..4
    doc.add_heading(heading_text, level=level)
    _write_items(doc, section.children)


def _write_items(doc: DocxDocument, items: Sequence[LogicalSection | Block]) -> None:
    """Рекурсивно записать смешанный список логических разделов и блоков."""
    for item in items:
        if isinstance(item, LogicalSection):
            _write_logical_section(doc, item)
        elif isinstance(item, Paragraph):
            _write_paragraph(doc, item)
        # Table/Figure/Formula — Фаза 1+


def export_docx(document: Document, profile: Profile, output_path: str | Path) -> None:
    """Собрать .docx из модели по профилю.

    Минимальная реализация: геометрия страницы, стиль Normal, параграфы и
    заголовки. PageSection обрабатываются последовательно, но все кладутся
    в одну физическую секцию docx (sectPr per-PageSection — Фаза 2).
    """
    output_path = Path(output_path)
    doc = docx.Document()

    _apply_page_geometry(doc, profile)
    _apply_normal_style(doc, profile)

    for page_section in document.page_sections:
        _write_items(doc, page_section.content)

    doc.save(str(output_path))
