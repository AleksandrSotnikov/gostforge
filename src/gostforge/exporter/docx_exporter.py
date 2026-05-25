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

    # Случай 1: embedded:rIdN с открытым source_docx.
    if path.startswith("embedded:") and _current_source_docx is not None:
        rid = path[len("embedded:"):]
        if _try_write_embedded_picture(doc, _current_source_docx, rid, figure):
            return

    # Случай 2: реальный файл на диске.
    if path and not path.startswith("embedded:") and Path(path).is_file():
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        try:
            run.add_picture(path)
        except Exception:  # noqa: BLE001 — fallback на placeholder при любой ошибке
            paragraph.add_run(f"[Рисунок: {figure.id}]").italic = True
        _write_caption_paragraph(doc, figure.caption)
        return

    # Случай 3: placeholder.
    placeholder = doc.add_paragraph()
    placeholder.add_run(f"[Рисунок: {figure.id}]").italic = True
    _write_caption_paragraph(doc, figure.caption)


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
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    try:
        run.add_picture(io.BytesIO(blob))
    except Exception:  # noqa: BLE001
        p_xml = paragraph._p
        parent = p_xml.getparent()
        if parent is not None:
            parent.remove(p_xml)
        return False

    _write_caption_paragraph(doc, figure.caption)
    return True


def _write_list(doc: DocxDocument, list_block: ListBlock) -> None:
    """Записать список (нумерованный/маркированный).

    Используем Word-стили ``List Number`` / ``List Bullet``, если они
    доступны в шаблоне. Если стиль недоступен — fallback на обычный
    параграф с текстовым префиксом «1. » или «• ».
    """
    style_name = "List Number" if list_block.ordered else "List Bullet"
    for idx, item_content in enumerate(list_block.items, start=1):
        try:
            paragraph = doc.add_paragraph(style=style_name)
        except KeyError:
            paragraph = doc.add_paragraph()
            prefix = f"{idx}. " if list_block.ordered else "• "
            paragraph.add_run(prefix)
        _write_runs(paragraph, item_content)


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
    global _current_source_docx, _current_bibliography_index
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

        # Метаданные документа в docProps/core.xml.
        core = doc.core_properties
        if document.metadata.title:
            core.title = document.metadata.title
        if document.metadata.author:
            core.author = document.metadata.author

        if document.page_sections:
            first = document.page_sections[0]
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
