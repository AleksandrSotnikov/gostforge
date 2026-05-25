"""Экспорт модели документа в .docx с применением стилей профиля.

Реализация Фазы 1:
- Поля страницы из профиля
- Стиль Normal (шрифт, кегль, межстрочный интервал, отступ первой строки)
- Параграфы со склейкой TextRun-ов и сохранением форматирования
- Per-paragraph переопределения (alignment, line_spacing, first_line_indent,
  page_break_before)
- Логические разделы как заголовки соответствующего уровня
- Таблицы с подписями и шапкой
- Рисунки экспортируются как заглушка-параграф (image_path не сохраняем
  на Фазе 1 — это потребует копирования media в docx)

Дальнейшие фазы (sectPr per-PageSection, header/footer-part, поля
PAGE/STYLEREF, реальные изображения, OMML-формулы) — отдельные итерации.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import docx  # type: ignore[import-not-found]
from docx.document import Document as DocxDocument  # type: ignore[import-not-found]
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore[import-not-found]
from docx.shared import Cm, Mm, Pt  # type: ignore[import-not-found]
from docx.text.paragraph import Paragraph as DocxParagraph  # type: ignore[import-not-found]

from gostforge.model import (
    Block,
    Document,
    Figure,
    InlineElement,
    LogicalSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import Profile


_ALIGNMENT_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


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


def _apply_paragraph_format(docx_para: DocxParagraph, paragraph: Paragraph) -> None:
    """Применить per-paragraph переопределения формата (если заданы в модели)."""
    pf = docx_para.paragraph_format
    if paragraph.alignment is not None:
        pf.alignment = _ALIGNMENT_MAP[paragraph.alignment]
    if paragraph.line_spacing is not None:
        pf.line_spacing = paragraph.line_spacing
    if paragraph.first_line_indent_cm is not None:
        pf.first_line_indent = Cm(paragraph.first_line_indent_cm)
    if paragraph.page_break_before is not None:
        pf.page_break_before = paragraph.page_break_before


def _write_paragraph(doc: DocxDocument, paragraph: Paragraph) -> None:
    """Добавить один Paragraph в docx-документ."""
    style_name = paragraph.style_name or "Normal"
    try:
        docx_para = doc.add_paragraph(style=style_name)
    except KeyError:
        # Неизвестный стиль (например, кастомное имя) — используем Normal.
        docx_para = doc.add_paragraph(style="Normal")
    _apply_paragraph_format(docx_para, paragraph)
    _write_runs(docx_para, paragraph.content)


def _write_logical_section(doc: DocxDocument, section: LogicalSection) -> None:
    """Добавить заголовок логического раздела и рекурсивно записать его содержимое."""
    heading_text = "".join(
        el.text for el in section.heading if isinstance(el, TextRun)
    )
    level = max(0, min(section.level, 4))  # docx supports 0..9, мы — 1..4
    doc.add_heading(heading_text, level=level)
    _write_items(doc, section.children)


def _write_caption_paragraph(doc: DocxDocument, content: Sequence[InlineElement]) -> None:
    """Записать подпись (Caption) отдельным параграфом со стилем «Caption»."""
    if not content:
        return
    try:
        docx_para = doc.add_paragraph(style="Caption")
    except KeyError:
        docx_para = doc.add_paragraph()
    _write_runs(docx_para, content)


def _write_table(doc: DocxDocument, table: Table) -> None:
    """Записать таблицу с подписью НАД ней (по ГОСТ).

    Шапка пишется первой строкой со стилем bold. Дополнительные ряды — обычные.
    Подписи рисунков идут под рисунком, подписи таблиц — над ней.
    """
    _write_caption_paragraph(doc, table.caption)
    column_count = len(table.headers) if table.headers else 0
    for row in table.rows:
        column_count = max(column_count, len(row))
    if column_count == 0:
        return

    rows_total = (1 if table.headers else 0) + len(table.rows)
    if rows_total == 0:
        return
    docx_table = doc.add_table(rows=rows_total, cols=column_count)
    row_idx = 0
    if table.headers:
        for col_idx, cell_content in enumerate(table.headers):
            cell = docx_table.rows[row_idx].cells[col_idx]
            cell.text = ""
            _write_runs(cell.paragraphs[0], cell_content)
            for run in cell.paragraphs[0].runs:
                run.bold = True
        row_idx += 1
    for row in table.rows:
        for col_idx, cell_content in enumerate(row):
            if col_idx >= column_count:
                break
            cell = docx_table.rows[row_idx].cells[col_idx]
            cell.text = ""
            _write_runs(cell.paragraphs[0], cell_content)
        row_idx += 1


def _write_figure(doc: DocxDocument, figure: Figure) -> None:
    """Записать рисунок-заглушку и подпись.

    На Фазе 1 image_path не материализуется — пишем placeholder-параграф
    `[Рисунок: <id>]`. Реальная вставка изображений — Фаза 2 (нужно
    копирование media-файла в docx-архив).
    """
    placeholder = doc.add_paragraph()
    placeholder.add_run(f"[Рисунок: {figure.id}]").italic = True
    _write_caption_paragraph(doc, figure.caption)


def _write_items(doc: DocxDocument, items: Sequence[LogicalSection | Block]) -> None:
    """Рекурсивно записать смешанный список логических разделов и блоков."""
    for item in items:
        if isinstance(item, LogicalSection):
            _write_logical_section(doc, item)
        elif isinstance(item, Paragraph):
            _write_paragraph(doc, item)
        elif isinstance(item, Table):
            _write_table(doc, item)
        elif isinstance(item, Figure):
            _write_figure(doc, item)
        # Formula — Фаза 3 (OMML)


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
