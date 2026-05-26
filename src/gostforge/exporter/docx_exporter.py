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

import io
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import docx  # type: ignore[import-not-found]
from docx.document import Document as DocxDocument  # type: ignore[import-not-found]
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore[import-not-found]
from docx.oxml import OxmlElement  # type: ignore[import-not-found]
from docx.oxml.ns import qn  # type: ignore[import-not-found]
from docx.shared import Cm, Mm, Pt, RGBColor  # type: ignore[import-not-found]
from docx.text.paragraph import Paragraph as DocxParagraph  # type: ignore[import-not-found]

from gostforge.model import (
    Block,
    Citation,
    ContentTemplate,
    CrossRef,
    Document,
    Figure,
    Formula,
    InlineElement,
    InlineFormula,
    ListBlock,
    LogicalSection,
    PageSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import Profile

# Локальные импорты lxml — нужны только для записи поля PAGE в footer.
# Парсер уже использует ту же lxml-цепочку для чтения.
from lxml import etree  # type: ignore[import-untyped]


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

logger = logging.getLogger(__name__)

# Контекст для одной операции экспорта: открытый исходный документ, из
# которого парсился `document`. Используется только в _write_figure для
# вставки реальных изображений (`embedded:rIdN`). Threading-небезопасно —
# для CLI и тестов достаточно; при необходимости можно перенести в
# ContextVar.
_current_source_docx: Any | None = None

# Контекст одной операции экспорта: 1-based индексы записей библиографии
# по их id. Используется в `_write_runs` для рендеринга Citation. Сбрасывается
# в `export_docx()` через try/finally, чтобы состояние не утекало между вызовами.
_current_bibliography_index: dict[str, int] | None = None

# Контекст одной операции экспорта: профиль для доступа к heading/caption/
# table-стилям внутри функций записи. Заполняется в export_docx() и
# сбрасывается через try/finally.
_current_profile: Any | None = None

_ALIGNMENT_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}

# Плейсхолдер, который парсер ставит при обнаружении поля PAGE; при
# экспорте мы материализуем его обратно в <w:fldSimple w:instr="PAGE"/>.
_PAGE_PLACEHOLDER = "{page}"


# Размеры бумаги в мм (портретная ориентация: short, long).
_PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A5": (148.0, 210.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
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


def _apply_page_size(doc: DocxDocument, page_section: PageSection) -> None:
    """Применить paper size и orientation из PageSection к первой docx-секции.

    Если paper неизвестен — оставляем дефолт Word. Если orientation =
    landscape — width и height меняются местами относительно portrait.
    """
    paper = page_section.page.paper
    if paper not in _PAPER_SIZES_MM:
        return
    short, long_ = _PAPER_SIZES_MM[paper]
    if page_section.page.orientation == "landscape":
        width, height = long_, short
    else:
        width, height = short, long_
    sect = doc.sections[0]
    sect.page_width = Mm(width)
    sect.page_height = Mm(height)


def _apply_normal_style(doc: DocxDocument, profile: Profile) -> None:
    """Применить шрифт/кегль/интервалы к стилю Normal.

    Дополнительно зануляет theme-fonts (asciiTheme/hAnsiTheme),
    которые Word из дефолтного шаблона ставит как majorHAnsi/minorHAnsi
    и которые при render-е в Word/LibreOffice перекрывают явно
    указанный font.name.
    """
    body = profile.styles.body
    normal = doc.styles["Normal"]
    normal.font.name = body.font
    normal.font.size = Pt(body.size_pt)
    # Снимаем theme-fonts со стиля Normal, иначе в Word шрифт может
    # отображаться как Calibri/Cambria поверх явно указанного.
    _clear_theme_fonts(normal.element, font_name=body.font)
    pf = normal.paragraph_format
    pf.line_spacing = body.line_spacing
    pf.first_line_indent = Cm(body.first_line_indent_cm)


def _clear_theme_fonts(style_element: Any, *, font_name: str) -> None:
    """Удалить theme-атрибуты у w:rFonts и проставить явный шрифт.

    Word при создании документа через python-docx наследует stлей Normal
    из бортового шаблона: rFonts с asciiTheme/hAnsiTheme = minorHAnsi
    (Calibri). Это перекрывает явно заданный font.name при рендере.
    Решение — найти w:rFonts в xml-элементе стиля, убрать
    *Theme-атрибуты и проставить ascii/hAnsi/cs/eastAsia на нужный шрифт.
    """
    w_ns = W_NS
    rPr = style_element.find(f"{{{w_ns}}}rPr")
    if rPr is None:
        return
    rFonts = rPr.find(f"{{{w_ns}}}rFonts")
    if rFonts is None:
        rFonts = etree.SubElement(rPr, f"{{{w_ns}}}rFonts")
    # Снимаем theme-атрибуты.
    for attr in (
        "asciiTheme",
        "hAnsiTheme",
        "cstheme",
        "eastAsiaTheme",
    ):
        key = f"{{{w_ns}}}{attr}"
        if key in rFonts.attrib:
            del rFonts.attrib[key]
    # Ставим явный шрифт для всех 4 наборов символов.
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        rFonts.set(f"{{{w_ns}}}{attr}", font_name)


def _apply_heading_styles(doc: DocxDocument, profile: Profile) -> None:
    """Переопределить стили Heading1..Heading4 параметрами из профиля.

    python-docx наследует Heading-стили из бортового шаблона Word —
    там они синие, Cambria, с большими before-spacing. Эта функция
    их переписывает по `profile.styles.heading_N`.
    """
    levels = (
        (1, profile.styles.heading_1),
        (2, profile.styles.heading_2),
        (3, profile.styles.heading_3),
        (4, profile.styles.heading_4),
    )
    for level, cfg in levels:
        style_id = f"Heading {level}"
        try:
            style = doc.styles[style_id]
        except KeyError:  # pragma: no cover - python-docx делает Heading1..9
            continue
        # Font + theme cleanup.
        style.font.name = cfg.font
        style.font.size = Pt(cfg.size_pt)
        style.font.bold = cfg.bold
        style.font.italic = cfg.italic
        # Цвет: 'auto' = снять явный цвет, иначе hex.
        _apply_style_color(style.element, cfg.color)
        _clear_theme_fonts(style.element, font_name=cfg.font)
        # Параграф-формат.
        pf = style.paragraph_format
        pf.alignment = _ALIGNMENT_MAP[cfg.alignment]
        pf.line_spacing = cfg.line_spacing
        pf.space_before = Pt(cfg.spacing_before_pt)
        pf.space_after = Pt(cfg.spacing_after_pt)
        pf.first_line_indent = Cm(cfg.first_line_indent_cm)
        pf.page_break_before = cfg.page_break_before
        pf.keep_with_next = cfg.keep_with_next
        # Связанный character-стиль (HeadingNChar): Word при рендере run-ов
        # внутри параграфа применяет linked-char поверх параграф-стиля.
        # Если не переписать — Cambria+синий из дефолтного шаблона
        # перекроют нашу правку.
        _sync_linked_char_style(doc, style.element, cfg)


def _sync_linked_char_style(doc: DocxDocument, p_style_element: Any, cfg: Any) -> None:
    """Применить шрифт/цвет/жирность из cfg к linked character-стилю.

    В styles.xml у каждого heading-параграф-стиля есть ссылка
    ``<w:link w:val="HeadingNChar"/>`` на character-стиль. При рендере
    run-ов параграфа Word применяет char-стиль поверх параграф-стиля
    (и его theme-fonts/синий цвет могут перекрыть параграф-настройки).

    Эта функция находит linked-char-стиль по styleId из w:link и
    переписывает его font, color, bold, italic симметрично с
    параграф-стилем. theme-fonts чистятся через _clear_theme_fonts.
    """
    w_ns = W_NS
    link = p_style_element.find(f"{{{w_ns}}}link")
    if link is None:
        return
    char_style_id = link.get(f"{{{w_ns}}}val")
    if not char_style_id:
        return
    # python-docx не индексирует character-стили по styleId напрямую,
    # ищем через styles_part.element.
    styles_root = p_style_element.getparent()
    char_elem = None
    for st in styles_root.findall(f"{{{w_ns}}}style"):
        if (
            st.get(f"{{{w_ns}}}type") == "character"
            and st.get(f"{{{w_ns}}}styleId") == char_style_id
        ):
            char_elem = st
            break
    if char_elem is None:
        return
    # Font + theme cleanup на rPr этого char-стиля.
    _clear_theme_fonts(char_elem, font_name=cfg.font)
    rPr = char_elem.find(f"{{{w_ns}}}rPr")
    if rPr is None:
        rPr = etree.SubElement(char_elem, f"{{{w_ns}}}rPr")
    # Size: w:sz/w:szCs в полу-пунктах (Pt*2).
    half_pt = str(int(cfg.size_pt * 2))
    for tag in ("sz", "szCs"):
        el = rPr.find(f"{{{w_ns}}}{tag}")
        if el is None:
            el = etree.SubElement(rPr, f"{{{w_ns}}}{tag}")
        el.set(f"{{{w_ns}}}val", half_pt)
    # Bold / italic: явные w:b и w:i (или их удаление).
    for tag, want in (("b", cfg.bold), ("bCs", cfg.bold), ("i", cfg.italic), ("iCs", cfg.italic)):
        el = rPr.find(f"{{{w_ns}}}{tag}")
        if want:
            if el is None:
                etree.SubElement(rPr, f"{{{w_ns}}}{tag}")
        else:
            if el is not None:
                rPr.remove(el)
    # Color — через ту же функцию что и для параграф-стиля.
    _apply_style_color(char_elem, cfg.color)


def _apply_style_color(style_element: Any, color: str) -> None:
    """Установить или снять явный цвет шрифта на уровне стиля.

    'auto' (или пустая строка) — снимает атрибут (Word возьмёт чёрный).
    hex без # — ставит rgb-цвет.
    """
    w_ns = W_NS
    rPr = style_element.find(f"{{{w_ns}}}rPr")
    if rPr is None:
        rPr = etree.SubElement(style_element, f"{{{w_ns}}}rPr")
    color_elem = rPr.find(f"{{{w_ns}}}color")
    if color in ("auto", "", None):
        if color_elem is not None:
            rPr.remove(color_elem)
        # Также удалим theme-color если есть.
        return
    if color_elem is None:
        color_elem = etree.SubElement(rPr, f"{{{w_ns}}}color")
    # Удалим тема-атрибуты, чтобы наш val реально применился.
    for attr in ("themeColor", "themeTint", "themeShade"):
        key = f"{{{w_ns}}}{attr}"
        if key in color_elem.attrib:
            del color_elem.attrib[key]
    color_elem.set(f"{{{w_ns}}}val", color.lstrip("#"))


def _apply_caption_style(doc: DocxDocument, profile: Profile) -> None:
    """Применить параметры подписи к стилю Caption (для figure и table).

    Поскольку figure.caption и table.caption могут отличаться (центр
    vs. лево, выше/ниже) — стиль Caption переписываем по figure.caption,
    а отдельные настройки для подписи таблицы применяются прямо к
    параграфу при записи таблицы (см. _write_table_caption).
    """
    cfg = profile.styles.figure.caption
    try:
        style = doc.styles["Caption"]
    except KeyError:  # pragma: no cover
        return
    style.font.name = cfg.font
    style.font.size = Pt(cfg.size_pt)
    style.font.bold = cfg.bold
    style.font.italic = cfg.italic
    _clear_theme_fonts(style.element, font_name=cfg.font)
    _apply_style_color(style.element, "auto")
    pf = style.paragraph_format
    pf.alignment = _ALIGNMENT_MAP[cfg.alignment]
    pf.space_before = Pt(cfg.spacing_before_pt)
    pf.space_after = Pt(cfg.spacing_after_pt)
    pf.first_line_indent = Cm(0)


def _write_runs(docx_paragraph: DocxParagraph, content: Sequence[InlineElement]) -> None:
    """Записать список InlineElement как набор run-ов в docx-параграф.

    Поддерживаются 4 типа inline-элементов (см. `gostforge.model.InlineElement`):

    * `TextRun` — обычный run с inline-форматированием.
    * `CrossRef` — OOXML-поле `<w:fldSimple w:instr=" REF target_id \\h "/>`;
      опциональный текст `prefix` добавляется как соседний run перед полем.
    * `InlineFormula` — `<m:oMath>` внутри `<w:r>` того же параграфа.
    * `Citation` — текстовый run «[N]» / «[N, с. P]», где N — 1-based индекс
      `source_id` в `Document.bibliography` (берётся из модуля).
    """
    for element in content:
        if isinstance(element, TextRun):
            _write_text_run(docx_paragraph, element)
        elif isinstance(element, CrossRef):
            _write_cross_ref(docx_paragraph, element)
        elif isinstance(element, InlineFormula):
            _write_inline_formula(docx_paragraph, element)
        elif isinstance(element, Citation):
            _write_citation(docx_paragraph, element)


def _write_text_run(docx_paragraph: DocxParagraph, element: TextRun) -> None:
    """Записать TextRun со всеми его inline-атрибутами форматирования."""
    run = docx_paragraph.add_run(element.text)
    if element.bold:
        run.bold = True
    if element.italic:
        run.italic = True
    if element.underline:
        run.underline = True
    if element.superscript:
        run.font.superscript = True
    if element.subscript:
        run.font.subscript = True
    if element.font:
        run.font.name = element.font
    if element.size_pt is not None:
        run.font.size = Pt(element.size_pt)
    if element.color_hex:
        # color_hex в модели хранится как "#RRGGBB"; RGBColor ждёт hex без "#".
        hex_value = element.color_hex.lstrip("#")
        try:
            run.font.color.rgb = RGBColor.from_string(hex_value)
        except (ValueError, TypeError):
            # Невалидный цвет — игнорируем, не ломаем экспорт ради одного run.
            logger.debug("Невалидный color_hex=%r, пропускаем", element.color_hex)


def _write_cross_ref(docx_paragraph: DocxParagraph, element: CrossRef) -> None:
    """Записать CrossRef как опциональный prefix-run + `<w:fldSimple>` с REF.

    Display-текст внутри fldSimple — placeholder «[?]»: Word подменит его
    реальной автонумерацией при первом пересчёте полей. Для проверок C.*
    важно наличие правильного `w:instr` в OOXML.
    """
    if element.prefix:
        docx_paragraph.add_run(element.prefix)
    fld = OxmlElement("w:fldSimple")
    # Стандартный синтаксис Word: REF <bookmark> \h (гиперссылка). Пробелы
    # вокруг target_id критичны — без них Word не распарсит инструкцию.
    fld.set(qn("w:instr"), f" REF {element.target_id} \\h ")
    # Word рендерит fldSimple только при наличии хотя бы одного <w:r> внутри.
    inner_run = OxmlElement("w:r")
    inner_t = OxmlElement("w:t")
    inner_t.text = "[?]"
    inner_run.append(inner_t)
    fld.append(inner_run)
    docx_paragraph._p.append(fld)


def _write_inline_formula(docx_paragraph: DocxParagraph, element: InlineFormula) -> None:
    """Записать InlineFormula как `<m:oMath>` ВНУТРИ `<w:r>` параграфа.

    В отличие от блочной `Formula`, inline-формула не оборачивается в
    `<m:oMathPara>` и идёт в потоке текста. На Фазе 2.5 используется
    простейший fallback: LaTeX-строка кладётся в `<m:t>` как обычный текст;
    парсер уже умеет читать такой формат.
    """
    w_run = OxmlElement("w:r")
    omath = etree.SubElement(w_run, f"{{{M_NS}}}oMath")
    m_r = etree.SubElement(omath, f"{{{M_NS}}}r")
    m_t = etree.SubElement(m_r, f"{{{M_NS}}}t")
    m_t.text = element.latex
    docx_paragraph._p.append(w_run)


def _write_citation(docx_paragraph: DocxParagraph, element: Citation) -> None:
    """Записать Citation как текстовый run «[N]» / «[N, с. P]».

    Номер N вычисляется из модуль-level карты `_current_bibliography_index`,
    проставленной `export_docx()`. Если карта пуста или источник не найден,
    подставляем «?» (это всё ещё корректный текст, но проверка R.04 такой
    цитаты не пропустит — что и нужно).
    """
    index_map = _current_bibliography_index or {}
    n_value: int | str = index_map.get(element.source_id, "?")
    text = element.template.format(n=n_value, pages=element.pages or "")
    docx_paragraph.add_run(text)


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
    """Добавить заголовок логического раздела и рекурсивно записать его содержимое.

    Применяет UPPERCASE если профиль это требует для текущего уровня
    (по умолчанию — для heading_1 в ГОСТ 7.32).
    """
    heading_text = "".join(
        el.text for el in section.heading if isinstance(el, TextRun)
    )
    level = max(0, min(section.level, 4))  # docx supports 0..9, мы — 1..4
    # Профиль-конфиг уровня: heading_1..heading_4 → uppercase, прочее.
    if _current_profile is not None and 1 <= level <= 4:
        cfg = getattr(_current_profile.styles, f"heading_{level}", None)
        if cfg is not None and cfg.uppercase:
            heading_text = heading_text.upper()
    doc.add_heading(heading_text, level=level)
    _write_items(doc, section.children)


def _write_caption_paragraph(
    doc: DocxDocument,
    content: Sequence[InlineElement],
    *,
    caption_kind: Literal["figure", "table"] = "figure",
) -> None:
    """Записать подпись отдельным параграфом со стилем «Caption».

    `caption_kind` определяет, какой `CaptionStyleProfile` использовать —
    figure (по центру под рисунком) или table (слева над таблицей).
    Без него используем стиль figure-подписи (исторический default).
    """
    if not content:
        return
    try:
        docx_para = doc.add_paragraph(style="Caption")
    except KeyError:
        docx_para = doc.add_paragraph()
    _write_runs(docx_para, content)
    # Применяем alignment и spacing согласно профилю — стиль Caption общий,
    # а для table-подписи нужны другие настройки (слева, перед таблицей).
    if _current_profile is None:
        return
    if caption_kind == "table":
        cfg = _current_profile.styles.table.caption
    else:
        cfg = _current_profile.styles.figure.caption
    pf = docx_para.paragraph_format
    pf.alignment = _ALIGNMENT_MAP[cfg.alignment]
    pf.space_before = Pt(cfg.spacing_before_pt)
    pf.space_after = Pt(cfg.spacing_after_pt)
    pf.first_line_indent = Cm(0)
    # На уровне run-ов — шрифт/кегль (если в стиле Caption они сбиты).
    for run in docx_para.runs:
        run.font.name = cfg.font
        run.font.size = Pt(cfg.size_pt)
        if cfg.bold:
            run.bold = True
        if cfg.italic:
            run.italic = True


def _write_table(doc: DocxDocument, table: Table) -> None:
    """Записать таблицу с подписью НАД ней (по ГОСТ).

    Применяет рамки и стиль ячеек из ``profile.styles.table``. Шапка
    bold. Подпись таблицы — слева, ВЫШЕ таблицы (профиль).
    """
    _write_caption_paragraph(doc, table.caption, caption_kind="table")
    column_count = len(table.headers) if table.headers else 0
    for row in table.rows:
        column_count = max(column_count, len(row))
    if column_count == 0:
        return

    rows_total = (1 if table.headers else 0) + len(table.rows)
    if rows_total == 0:
        return
    docx_table = doc.add_table(rows=rows_total, cols=column_count)

    # Применяем стиль таблицы (рамки + шрифт ячеек) из профиля.
    cfg = (
        _current_profile.styles.table
        if _current_profile is not None
        else None
    )
    if cfg is not None:
        _apply_table_borders(docx_table, cfg)

    row_idx = 0
    if table.headers:
        header_bold = cfg.header_bold if cfg is not None else True
        for col_idx, cell_content in enumerate(table.headers):
            cell = docx_table.rows[row_idx].cells[col_idx]
            cell.text = ""
            _write_runs(cell.paragraphs[0], cell_content)
            _apply_cell_font(cell, cfg)
            if header_bold:
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
            _apply_cell_font(cell, cfg)
        row_idx += 1


def _apply_table_borders(docx_table: Any, cfg: Any) -> None:
    """Прокинуть рамки в OOXML таблицы через w:tblBorders.

    python-docx позволяет задать ``table.style`` строкой ("Table Grid"),
    но стиль может отсутствовать в bortоvom шаблоне. Надёжнее —
    написать ``<w:tblBorders>`` напрямую в XML свойств таблицы.
    """
    if cfg.border_style == "none":
        return
    tbl_pr = docx_table._element.find(f"{{{W_NS}}}tblPr")
    if tbl_pr is None:
        tbl_pr = etree.SubElement(docx_table._element, f"{{{W_NS}}}tblPr")
    # Если tblBorders уже есть — заменим, иначе создадим.
    existing = tbl_pr.find(f"{{{W_NS}}}tblBorders")
    if existing is not None:
        tbl_pr.remove(existing)
    borders = etree.SubElement(tbl_pr, f"{{{W_NS}}}tblBorders")
    color = "auto" if cfg.border_color == "auto" else cfg.border_color.lstrip("#")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = etree.SubElement(borders, f"{{{W_NS}}}{side}")
        el.set(f"{{{W_NS}}}val", cfg.border_style)
        el.set(f"{{{W_NS}}}sz", str(int(cfg.border_size)))
        el.set(f"{{{W_NS}}}space", "0")
        el.set(f"{{{W_NS}}}color", color)


def _apply_cell_font(cell: Any, cfg: Any) -> None:
    """Применить шрифт/кегль ячеек таблицы, если они заданы в профиле.

    Если cell_font / cell_size_pt = None — оставляем дефолт от стиля Normal
    (который уже Times New Roman через _apply_normal_style).
    """
    if cfg is None:
        return
    if cfg.cell_font is None and cfg.cell_size_pt is None:
        return
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            if cfg.cell_font is not None:
                run.font.name = cfg.cell_font
            if cfg.cell_size_pt is not None:
                run.font.size = Pt(cfg.cell_size_pt)


def _write_figure(doc: DocxDocument, figure: Figure) -> None:
    """Записать рисунок и его подпись.

    Стратегия выбора источника изображения:

    1. ``image_path = "embedded:rIdN"`` — рисунок пришёл из парсера и
       ссылается на media-blob исходного .docx. Если в текущем контексте
       экспорта (`_current_source_docx`) открыт source_docx — копируем
       blob и вставляем как настоящее изображение.
    2. ``image_path`` указывает на существующий файл — `add_picture(path)`.
    3. Иначе (пусто, не-файл, ошибка вставки) — placeholder-параграф
       вида `[Рисунок: <id>]`.
    """
    path = figure.image_path

    fig_alignment = _figure_alignment_from_profile()

    # Случай 1: embedded:rIdN с открытым source_docx.
    if path.startswith("embedded:") and _current_source_docx is not None:
        rid = path[len("embedded:"):]
        if _try_write_embedded_picture(doc, _current_source_docx, rid, figure):
            return

    # Случай 2: реальный файл на диске.
    if path and not path.startswith("embedded:") and Path(path).is_file():
        paragraph = doc.add_paragraph()
        paragraph.alignment = fig_alignment
        # Первый отступ убираем — это не текст, а рисунок.
        paragraph.paragraph_format.first_line_indent = Cm(0)
        run = paragraph.add_run()
        try:
            run.add_picture(path)
        except Exception:  # noqa: BLE001 — fallback на placeholder при любой ошибке
            paragraph.add_run(f"[Рисунок: {figure.id}]").italic = True
        _write_caption_paragraph(doc, figure.caption, caption_kind="figure")
        return

    # Случай 3: placeholder.
    placeholder = doc.add_paragraph()
    placeholder.alignment = fig_alignment
    placeholder.paragraph_format.first_line_indent = Cm(0)
    placeholder.add_run(f"[Рисунок: {figure.id}]").italic = True
    _write_caption_paragraph(doc, figure.caption, caption_kind="figure")


def _figure_alignment_from_profile() -> Any:
    """Вернуть выравнивание рисунка из профиля (или CENTER по умолчанию)."""
    if _current_profile is None:
        return WD_ALIGN_PARAGRAPH.CENTER
    return _ALIGNMENT_MAP[_current_profile.styles.figure.alignment]


def _write_formula(doc: DocxDocument, formula: Formula) -> None:
    """Записать формулу как OOXML-OMath блок."""
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_xml = paragraph._p

    omath_para = etree.SubElement(p_xml, f"{{{M_NS}}}oMathPara")
    omath = etree.SubElement(omath_para, f"{{{M_NS}}}oMath")
    if formula.latex:
        m_r = etree.SubElement(omath, f"{{{M_NS}}}r")
        m_t = etree.SubElement(m_r, f"{{{M_NS}}}t")
        m_t.text = formula.latex

    if formula.number is not None:
        run = paragraph.add_run(f"\t({formula.number})")
        run.italic = False


def _try_write_embedded_picture(
    doc: DocxDocument, source_docx_obj: Any, rid: str, figure: Figure
) -> bool:
    """Попытка достать media-blob из source_docx и вставить как картинку."""
    try:
        image_part = source_docx_obj.part.related_parts.get(rid)
    except Exception:  # noqa: BLE001
        logger.debug("Не удалось получить related_parts для rId=%s", rid)
        return False
    if image_part is None:
        return False
    try:
        blob = image_part.blob
    except Exception:  # noqa: BLE001
        return False

    paragraph = doc.add_paragraph()
    paragraph.alignment = _figure_alignment_from_profile()
    paragraph.paragraph_format.first_line_indent = Cm(0)
    run = paragraph.add_run()
    try:
        run.add_picture(io.BytesIO(blob))
    except Exception:  # noqa: BLE001
        p_xml = paragraph._p
        parent = p_xml.getparent()
        if parent is not None:
            parent.remove(p_xml)
        return False

    _write_caption_paragraph(doc, figure.caption, caption_kind="figure")
    return True


def _write_list(doc: DocxDocument, list_block: ListBlock) -> None:
    """Записать список (нумерованный/маркированный) через настоящий numPr.

    Маркер и шаблон нумерации берутся из ``profile.styles.lists``
    (по умолчанию по ГОСТ Р 7.32-2017: маркер = тире «–»,
    нумерация = «N)»). Отступ слева и hanging — тоже из профиля.

    Стратегия: один раз на экспорт регистрируем в numbering.xml два
    abstractNum (ordered и bullet) с настроенным lvlText, и одно
    concrete num на каждый. Параграфы списка получают
    ``<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="N"/></w:numPr></w:pPr>``
    — Word/LibreOffice сами отрисовывают маркер. Это даёт правильное
    поведение списка при редактировании в Word (Enter → новый bullet),
    и парсер видит ``<w:numPr>`` → ListBlock без эвристик.
    """
    cfg = (
        _current_profile.styles.lists if _current_profile is not None else None
    )
    bullet = cfg.bullet_char if cfg is not None else "–"
    ordered_fmt = cfg.ordered_format if cfg is not None else "{n})"
    left_indent_cm = cfg.left_indent_cm if cfg is not None else 1.25
    hanging_indent_cm = cfg.hanging_indent_cm if cfg is not None else 0.5

    # lvlText для numbering.xml: %1 = подстановка номера, остальное —
    # литеральный текст. ordered_fmt из профиля имеет «{n}» — конвертируем.
    if list_block.ordered:
        lvl_text = ordered_fmt.replace("{n}", "%1")
    else:
        lvl_text = bullet
    num_id = _ensure_list_num_in_numbering(
        doc, ordered=list_block.ordered, lvl_text=lvl_text,
        left_twips=int(Cm(left_indent_cm).twips),
        hanging_twips=int(Cm(hanging_indent_cm).twips),
    )

    for item_content in list_block.items:
        paragraph = doc.add_paragraph()
        # Ставим numPr.
        pPr = paragraph._p.get_or_add_pPr()
        # Удалим существующий numPr на всякий случай.
        for old in pPr.findall(f"{{{W_NS}}}numPr"):
            pPr.remove(old)
        num_pr = etree.SubElement(pPr, f"{{{W_NS}}}numPr")
        ilvl = etree.SubElement(num_pr, f"{{{W_NS}}}ilvl")
        ilvl.set(f"{{{W_NS}}}val", "0")
        num_id_el = etree.SubElement(num_pr, f"{{{W_NS}}}numId")
        num_id_el.set(f"{{{W_NS}}}val", str(num_id))
        # Indent не нужен в pPr самого параграфа — он в abstractNum.
        # Но first_line_indent на 0 ставим, чтобы Normal-стиль не сдвигал текст.
        paragraph.paragraph_format.first_line_indent = Cm(0)
        _write_runs(paragraph, item_content)


# Кеш зарегистрированных numId внутри одного export-вызова: чтобы не
# плодить дубли abstractNum/num на каждый ListBlock. Ключ — кортеж
# (ordered, lvl_text, left_twips, hanging_twips). Сбрасывается в
# try/finally export_docx через _current_profile = None.
_current_list_numbering: dict[tuple[Any, ...], int] | None = None


def _ensure_list_num_in_numbering(
    doc: DocxDocument,
    *,
    ordered: bool,
    lvl_text: str,
    left_twips: int,
    hanging_twips: int,
) -> int:
    """Зарегистрировать (если ещё нет) abstractNum + num с этими параметрами.

    Возвращает numId, который нужно ставить в pPr/numPr/numId.

    Идея: на один уникальный (ordered+lvl_text+отступы) набор —
    один abstractNum и один num. Это позволяет иметь несколько списков
    с разной нумерацией (например, основной список с «N)» и доп.
    подсписок с «N.») в одном документе.
    """
    global _current_list_numbering
    if _current_list_numbering is None:
        _current_list_numbering = {}
    cache_key = (ordered, lvl_text, left_twips, hanging_twips)
    if cache_key in _current_list_numbering:
        return _current_list_numbering[cache_key]

    try:
        numbering_part = doc.part.numbering_part
    except (AttributeError, KeyError):  # pragma: no cover
        # numbering_part должен быть в дефолтном шаблоне python-docx,
        # но на всякий случай — возвращаем 0 (отсутствующий numId,
        # Word проигнорирует и параграф будет без маркера).
        return 0
    num_elem = numbering_part.element

    # Находим максимальный существующий abstractNumId и numId.
    max_anid = -1
    for an in num_elem.findall(f"{{{W_NS}}}abstractNum"):
        try:
            max_anid = max(
                max_anid, int(an.get(f"{{{W_NS}}}abstractNumId") or "-1")
            )
        except ValueError:
            pass
    max_nid = 0
    for n in num_elem.findall(f"{{{W_NS}}}num"):
        try:
            max_nid = max(max_nid, int(n.get(f"{{{W_NS}}}numId") or "0"))
        except ValueError:
            pass

    new_anid = max_anid + 1
    new_nid = max_nid + 1

    # Создаём <w:abstractNum>.
    an = etree.SubElement(num_elem, f"{{{W_NS}}}abstractNum")
    an.set(f"{{{W_NS}}}abstractNumId", str(new_anid))
    # multiLevelType: достаточно singleLevel — мы поддерживаем только 1 уровень.
    mlt = etree.SubElement(an, f"{{{W_NS}}}multiLevelType")
    mlt.set(f"{{{W_NS}}}val", "singleLevel")
    # Один уровень (ilvl=0).
    lvl = etree.SubElement(an, f"{{{W_NS}}}lvl")
    lvl.set(f"{{{W_NS}}}ilvl", "0")
    start = etree.SubElement(lvl, f"{{{W_NS}}}start")
    start.set(f"{{{W_NS}}}val", "1")
    num_fmt = etree.SubElement(lvl, f"{{{W_NS}}}numFmt")
    num_fmt.set(f"{{{W_NS}}}val", "decimal" if ordered else "bullet")
    lvl_text_el = etree.SubElement(lvl, f"{{{W_NS}}}lvlText")
    lvl_text_el.set(f"{{{W_NS}}}val", lvl_text)
    lvl_jc = etree.SubElement(lvl, f"{{{W_NS}}}lvlJc")
    lvl_jc.set(f"{{{W_NS}}}val", "left")
    # Параграф-настройки в lvl/pPr — для left+hanging indent.
    lvl_pPr = etree.SubElement(lvl, f"{{{W_NS}}}pPr")
    lvl_ind = etree.SubElement(lvl_pPr, f"{{{W_NS}}}ind")
    lvl_ind.set(f"{{{W_NS}}}left", str(left_twips))
    lvl_ind.set(f"{{{W_NS}}}hanging", str(hanging_twips))
    # Шрифт маркера: для bullet ставим обычный TNR, иначе Word возьмёт
    # Symbol и нарисует  — не наш тире.
    if not ordered:
        lvl_rPr = etree.SubElement(lvl, f"{{{W_NS}}}rPr")
        lvl_rFonts = etree.SubElement(lvl_rPr, f"{{{W_NS}}}rFonts")
        font = (
            _current_profile.styles.body.font
            if _current_profile is not None
            else "Times New Roman"
        )
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            lvl_rFonts.set(f"{{{W_NS}}}{attr}", font)

    # Создаём <w:num> ссылающийся на abstractNum.
    n = etree.SubElement(num_elem, f"{{{W_NS}}}num")
    n.set(f"{{{W_NS}}}numId", str(new_nid))
    abstract_ref = etree.SubElement(n, f"{{{W_NS}}}abstractNumId")
    abstract_ref.set(f"{{{W_NS}}}val", str(new_anid))

    _current_list_numbering[cache_key] = new_nid
    return new_nid


def _write_template_into_footer_paragraph(
    docx_paragraph: DocxParagraph, content: Sequence[InlineElement]
) -> None:
    """Записать содержимое одного слота footer/header, материализуя {page}.

    Каждый TextRun(text="{page}") превращается в OOXML-поле PAGE:
        <w:fldSimple w:instr="PAGE"/>
    Остальной текст пишется как обычные run-ы.
    """
    p_xml = docx_paragraph._p
    for element in content:
        if not isinstance(element, TextRun):
            continue
        # Разбиваем текст элемента на чередующиеся куски «обычный текст» / «{page}».
        text = element.text
        if not text:
            continue
        chunks = text.split(_PAGE_PLACEHOLDER)
        for i, chunk in enumerate(chunks):
            if chunk:
                docx_paragraph.add_run(chunk)
            if i < len(chunks) - 1:
                fld = etree.SubElement(p_xml, f"{{{W_NS}}}fldSimple")
                fld.set(f"{{{W_NS}}}instr", "PAGE")
                # Добавим внутрь fldSimple фиктивный run с пустым текстом —
                # без него Word не рендерит поле в новых версиях.
                run = etree.SubElement(fld, f"{{{W_NS}}}r")
                rt = etree.SubElement(run, f"{{{W_NS}}}t")
                rt.text = ""


def _has_text(items: Sequence[InlineElement] | None) -> bool:
    if not items:
        return False
    return any(
        isinstance(el, TextRun) and el.text and el.text.strip() for el in items
    )


def _write_footer(doc: DocxDocument, footer_template: ContentTemplate) -> None:
    """Записать footer из ContentTemplate в первую docx-секцию.

    Распределение по слотам left/center/right на Фазе 1 делаем через
    выравнивание единственного параграфа: если задан center — выравниваем
    по центру; right — вправо; иначе left. Если заполнены несколько слотов,
    добавляем отдельные параграфы под каждый.
    """
    section = doc.sections[0]
    footer = section.footer
    # Удалим параграфы-плейсхолдеры, которые python-docx создаёт по умолчанию
    # (один пустой <w:p/>).
    for p in list(footer.paragraphs):
        p_xml = p._p
        if p_xml.getparent() is not None and not p.text and not list(p_xml):
            p_xml.getparent().remove(p_xml)

    slots: list[tuple[str, Sequence[InlineElement] | None]] = [
        ("left", footer_template.left),
        ("center", footer_template.center),
        ("right", footer_template.right),
    ]

    for slot, content in slots:
        if not _has_text(content):
            continue
        assert content is not None  # ради mypy
        para = footer.add_paragraph()
        if slot == "center":
            para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif slot == "right":
            para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        else:
            para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _write_template_into_footer_paragraph(para, content)


# Обратное отображение модели в OOXML w:fmt (см. парсер _PAGE_FMT_MAP).
_PAGE_FMT_OOXML = {
    "arabic": "decimal",
    "roman": "upperRoman",
    "uppercase_letter": "upperLetter",
}


def _sync_page_section_with_profile(
    page_section: PageSection, profile: Profile
) -> None:
    """Применить параметры профиля к модели page_section перед записью.

    Согласует:
    * margins_mm — поля страницы из profile.styles.page;
    * page_numbering.start_value — из profile.checks['F.06'].params,
      если задано и текущий start_mode='start_at'.

    Эта функция мутирует input page_section (side effect). Это
    единственное место, где модель «приземляется» под конкретный
    профиль во время экспорта — builder.build() остаётся
    профиль-агностичным.
    """
    # Поля страницы.
    margins = profile.styles.page.margins_mm
    if margins:
        merged = dict(page_section.page.margins_mm)
        merged.update({k: float(v) for k, v in margins.items()})
        page_section.page.margins_mm = merged
    # F.06 start_value.
    f06 = profile.checks.get("F.06")
    if (
        f06
        and f06.enabled
        and f06.params.get("start_value") is not None
        and page_section.page_numbering.start_mode == "start_at"
    ):
        try:
            page_section.page_numbering.start_value = int(
                f06.params["start_value"]
            )
        except (TypeError, ValueError):
            pass


def _apply_pgnumtype(doc: DocxDocument, page_section: PageSection) -> None:
    """Прописать <w:pgNumType w:start="N" w:fmt="..."/> в sectPr.

    Атрибут `w:start` пишется только при `start_mode = "start_at"` и
    наличии `start_value`. Атрибут `w:fmt` пишется, если формат отличается
    от арабских цифр (Word-дефолт), либо если хоть один из атрибутов
    нужен — в этом случае пишем оба.
    """
    numbering = page_section.page_numbering
    needs_start = numbering.start_mode == "start_at" and numbering.start_value is not None
    needs_fmt = numbering.format != "arabic"
    if not needs_start and not needs_fmt:
        return
    sect = doc.sections[0]
    sect_pr = getattr(sect, "_sectPr", None)
    if sect_pr is None:
        return
    # Удаляем существующий pgNumType, чтобы не было дублей.
    for existing in sect_pr.findall(f"{{{W_NS}}}pgNumType"):
        sect_pr.remove(existing)
    pg = etree.SubElement(sect_pr, f"{{{W_NS}}}pgNumType")
    if needs_start:
        pg.set(f"{{{W_NS}}}start", str(numbering.start_value))
    if needs_fmt:
        pg.set(f"{{{W_NS}}}fmt", _PAGE_FMT_OOXML.get(numbering.format, "decimal"))


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
        elif isinstance(item, ListBlock):
            _write_list(doc, item)
        elif isinstance(item, Formula):
            _write_formula(doc, item)


def export_docx(
    document: Document,
    profile: Profile,
    output_path: str | Path,
    *,
    source_docx: str | Path | None = None,
) -> None:
    """Собрать .docx из модели по профилю.

    Минимальная реализация: геометрия страницы, стиль Normal, параграфы и
    заголовки. PageSection обрабатываются последовательно, но все кладутся
    в одну физическую секцию docx (sectPr per-PageSection — Фаза 2).

    Если у первой PageSection задан footer (например, после parse_docx
    плейсхолдер {page}) — он материализуется в OOXML-поле PAGE через lxml.

    Параметры:
      source_docx — путь к исходному .docx, из которого парсился document.
        Если задан и у Figure.image_path == ``embedded:rIdN``, экспортёр
        достанет соответствующий media-blob из source_docx и вставит как
        реальное изображение. Иначе на месте картинки будет placeholder.
    """
    global _current_source_docx, _current_bibliography_index, _current_profile, _current_list_numbering
    output_path = Path(output_path)
    doc = docx.Document()

    # Открываем source_docx (если задан) и кладём его в модуль-level
    # контекст — _write_figure читает оттуда. Try/finally гарантирует
    # сброс контекста даже при исключении в середине экспорта.
    _current_source_docx = None
    if source_docx is not None:
        try:
            _current_source_docx = docx.Document(str(source_docx))
        except Exception:
            # Повреждённый или нечитаемый docx → пропускаем источник, картинки уйдут в placeholder.
            logger.warning(
                "Не удалось открыть source_docx=%s; картинки будут placeholder-ами",
                source_docx,
            )
            _current_source_docx = None

    # Карта source_id → 1-based номер для рендеринга Citation. Заполняется
    # из Document.bibliography; пустая карта → все цитаты получат «?».
    _current_bibliography_index = {entry.id: i + 1 for i, entry in enumerate(document.bibliography)}

    try:
        _apply_page_geometry(doc, profile)
        _apply_normal_style(doc, profile)
        _apply_heading_styles(doc, profile)
        _apply_caption_style(doc, profile)
        _current_profile = profile

        # Метаданные документа в docProps/core.xml.
        core = doc.core_properties
        if document.metadata.title:
            core.title = document.metadata.title
        if document.metadata.author:
            core.author = document.metadata.author
        # Год работы: пишем как core.created (1 января указанного года),
        # чтобы парсер мог его прочитать обратно при impоrt-docx.
        # python-docx иначе ставит datetime.now(), и год потеряется.
        if document.metadata.year:
            from datetime import datetime, timezone  # noqa: PLC0415

            core.created = datetime(
                document.metadata.year, 1, 1, tzinfo=timezone.utc
            )

        if document.page_sections:
            first = document.page_sections[0]
            # Согласовать page_section с профилем перед записью: F.06
            # start_value, поля страницы. Builder ставит свои дефолты,
            # а профиль (особенно наследник base) может их переопределить.
            # Этот вызов — единое место синхронизации модели с профилем.
            _sync_page_section_with_profile(first, profile)
            _apply_page_size(doc, first)
            _apply_pgnumtype(doc, first)
            if first.footer is not None:
                _write_footer(doc, first.footer.default)
            if first.header is not None:
                _write_header(doc, first.header.default)

        for page_section in document.page_sections:
            _write_items(doc, page_section.content)

        doc.save(str(output_path))
    finally:
        _current_source_docx = None
        _current_bibliography_index = None
        _current_profile = None
        _current_list_numbering = None

    # Post-processing на уровне zip: запись настроек, которые python-docx
    # не умеет менять напрямую (например, w:autoHyphenation в settings.xml).
    _postprocess_zip(Path(output_path), document)


def _postprocess_zip(output_path: Path, document: Document) -> None:
    """Доработать .docx-архив после save(): записать настройки в settings.xml."""
    if document.auto_hyphenation is None:
        return
    _patch_settings_auto_hyphenation(output_path, document.auto_hyphenation)


def _patch_settings_auto_hyphenation(docx_path: Path, value: bool) -> None:
    """Прописать/удалить <w:autoHyphenation/> в word/settings.xml внутри docx-zip."""
    import shutil
    import zipfile
    settings_path = "word/settings.xml"
    tmp_path = docx_path.with_suffix(".docx.tmp")
    with zipfile.ZipFile(docx_path, "r") as zin, zipfile.ZipFile(
        tmp_path, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        names = zin.namelist()
        if settings_path not in names:
            settings_xml = (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"</w:settings>"
            )
        else:
            settings_xml = zin.read(settings_path)

        try:
            root = etree.fromstring(settings_xml)
            for existing in root.findall(f"{{{W_NS}}}autoHyphenation"):
                root.remove(existing)
            if value:
                elem = etree.SubElement(root, f"{{{W_NS}}}autoHyphenation")
                root.insert(0, elem)
            new_xml = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        except Exception:  # noqa: BLE001
            new_xml = settings_xml

        wrote_settings = False
        for name in names:
            if name == settings_path:
                zout.writestr(name, new_xml)
                wrote_settings = True
            else:
                zout.writestr(name, zin.read(name))
        if not wrote_settings:
            zout.writestr(settings_path, new_xml)

    shutil.move(str(tmp_path), str(docx_path))


def _write_header(doc: DocxDocument, header_template: ContentTemplate) -> None:
    """Записать содержимое header первой секции (зеркально _write_footer)."""
    section = doc.sections[0]
    header = section.header
    for p in list(header.paragraphs):
        p_xml = p._p
        if p_xml.getparent() is not None and not p.text and not list(p_xml):
            p_xml.getparent().remove(p_xml)

    slots: list[tuple[str, Sequence[InlineElement] | None]] = [
        ("left", header_template.left),
        ("center", header_template.center),
        ("right", header_template.right),
    ]

    for slot, content in slots:
        if not _has_text(content):
            continue
        assert content is not None
        para = header.add_paragraph()
        if slot == "center":
            para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif slot == "right":
            para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        else:
            para.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _write_template_into_footer_paragraph(para, content)
