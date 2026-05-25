"""Эвристический парсер .docx в модель документа.

Использует python-docx для базового разбора и lxml для нестандартных случаев
(колонтитулы, поля, ссылки). Работает эвристически: тип блока определяется
по стилю абзаца, паттернам в тексте, форматированию.

Поэтапная стратегия:
- Фаза 0: распознавать только параграфы и базовые свойства страницы
- Фаза 1: рисунки, таблицы, заголовки, нумерация
- Фаза 2: список литературы, перекрёстные ссылки, формулы
- Фаза 3: полный разбор колонтитулов, приложений
"""

# ruff: noqa: RUF002, RUF003

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import docx  # type: ignore[import-not-found]
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore[import-not-found]
from lxml import etree  # type: ignore[import-untyped]

from gostforge.model import (
    ContentTemplate,
    Document,
    DocumentMetadata,
    HeaderConfig,
    InlineElement,
    LogicalSection,
    PageGeometry,
    PageSection,
    Paragraph,
    ParagraphAlignment,
    TextRun,
)

if TYPE_CHECKING:
    DocxDocument = Any
    DocxSection = Any
    DocxParagraph = Any


# Пространство имён OOXML wordprocessingml
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}

# Соответствие WD_ALIGN_PARAGRAPH → строковая литералка модели
_ALIGN_MAP: dict[int, ParagraphAlignment] = {
    int(WD_ALIGN_PARAGRAPH.LEFT): "left",
    int(WD_ALIGN_PARAGRAPH.RIGHT): "right",
    int(WD_ALIGN_PARAGRAPH.CENTER): "center",
    int(WD_ALIGN_PARAGRAPH.JUSTIFY): "justify",
}

# Регэксп заголовков Word: "Heading 1", "Heading 2" и т.д.
_HEADING_RE = re.compile(r"^Heading\s+(\d+)$")


def parse_docx(path: str | Path) -> Document:
    """Прочитать .docx и вернуть модель документа.

    Возвращает Document с одной PageSection (id="main"), куда уложены
    LogicalSection-ы (по заголовкам) и Paragraph-ы.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    docx_doc = cast("DocxDocument", docx.Document(str(path)))

    metadata = _extract_metadata(docx_doc, fallback_title=path.stem)
    page_section = _extract_page_section(docx_doc)
    _populate_content(docx_doc, page_section)

    return Document(metadata=metadata, page_sections=[page_section])


# --- метаданные --------------------------------------------------------------


def _extract_metadata(docx_doc: DocxDocument, *, fallback_title: str) -> DocumentMetadata:
    """Извлечь title/author/year из docProps/core.xml."""
    core = docx_doc.core_properties
    title = (core.title or "").strip() or fallback_title
    author = (core.author or "").strip()
    year: int | None = None
    if core.created is not None:
        year = core.created.year
    return DocumentMetadata(title=title, author=author, year=year)


# --- секция страницы и колонтитулы -------------------------------------------


def _extract_page_section(docx_doc: DocxDocument) -> PageSection:
    """Построить PageSection из первой docx-секции (поля + footer)."""
    sect: DocxSection = docx_doc.sections[0]

    margins_mm = {
        "top": _length_to_mm(sect.top_margin),
        "right": _length_to_mm(sect.right_margin),
        "bottom": _length_to_mm(sect.bottom_margin),
        "left": _length_to_mm(sect.left_margin),
    }

    page_section = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(margins_mm=margins_mm),
    )

    # Стартовая страница нумерации: <w:pgNumType w:start="N"/> в sectPr.
    # Если атрибут задан — это эквивалентно start_mode = "start_at".
    start_value = _extract_page_number_start(sect)
    if start_value is not None:
        page_section.page_numbering.start_mode = "start_at"
        page_section.page_numbering.start_value = start_value

    footer_config = _extract_footer(sect)
    if footer_config is not None:
        page_section.footer = footer_config
        page_section.page_numbering.visible = True

    return page_section


def _extract_page_number_start(sect: DocxSection) -> int | None:
    """Прочитать <w:pgNumType w:start="N"/> из sectPr секции и вернуть N.

    Возвращает None, если элемент отсутствует или значение не парсится.
    """
    sect_pr = getattr(sect, "_sectPr", None)
    if sect_pr is None:
        return None
    pg_num_type = sect_pr.find(f"{{{W_NS}}}pgNumType")
    if pg_num_type is None:
        return None
    start_attr = pg_num_type.get(f"{{{W_NS}}}start")
    if start_attr is None:
        return None
    try:
        return int(start_attr)
    except (TypeError, ValueError):
        return None


def _length_to_mm(length: object | None) -> float:
    """Перевести python-docx Length в миллиметры (округление до 0.1 мм)."""
    if length is None:
        # Дефолты Word подставит сам python-docx; если значение отсутствует
        # после чтения секции — возвращаем 0.0, чтобы валидатор увидел это.
        return 0.0
    mm = float(length.mm)  # type: ignore[attr-defined]
    return round(mm, 1)


def _extract_footer(sect: DocxSection) -> HeaderConfig | None:
    """Прочитать footer секции и собрать HeaderConfig, если есть поле PAGE."""
    footer = sect.footer
    if footer is None:
        return None

    center_runs: list[InlineElement] = []

    for fp in footer.paragraphs:
        if not _paragraph_has_page_field(fp):
            continue
        alignment = _alignment_to_literal(fp.paragraph_format.alignment)
        # Центральная позиция определяется выравниванием по центру.
        # Если выравнивание иное — на Фазе 0 всё равно учитываем как центр,
        # т.к. отдельных левой/правой колонок в footer мы пока не строим.
        if alignment != "right":
            center_runs.append(TextRun(text="{page}"))
        # На Фазе 0 ограничиваемся одним маркером {page}.
        break

    if not center_runs:
        return None

    return HeaderConfig(default=ContentTemplate(center=center_runs))


def _paragraph_has_page_field(fp: DocxParagraph) -> bool:
    """Найти в абзаце поле PAGE (как fldSimple, так и через fldChar+instrText)."""
    p_xml = fp._p

    # Вариант 1: <w:fldSimple w:instr="PAGE">
    for fld in p_xml.findall(f"{{{W_NS}}}fldSimple"):
        instr = fld.get(f"{{{W_NS}}}instr") or ""
        if _instr_is_page(instr):
            return True

    # Вариант 2: пара fldChar + instrText
    instr_chunks: list[str] = []
    in_field = False
    for elem in p_xml.iter():
        tag = etree.QName(elem.tag).localname
        if tag == "fldChar":
            ftype = elem.get(f"{{{W_NS}}}fldCharType")
            if ftype == "begin":
                in_field = True
                instr_chunks = []
            elif ftype == "end" and in_field:
                combined = "".join(instr_chunks)
                if _instr_is_page(combined):
                    return True
                in_field = False
        elif tag == "instrText" and in_field:
            instr_chunks.append(elem.text or "")
    return False


def _instr_is_page(instr: str) -> bool:
    """Проверить, что инструкция поля содержит PAGE (но не NUMPAGES)."""
    tokens = instr.strip().split()
    if not tokens:
        return False
    return tokens[0].upper() == "PAGE"


# --- контент: параграфы и заголовки ------------------------------------------


def _populate_content(docx_doc: DocxDocument, page_section: PageSection) -> None:
    """Пройти по абзацам документа и распределить их по PageSection / LogicalSection.

    Стратегия Фазы 0: плоская иерархия. Заголовок (Heading N) создаёт новую
    LogicalSection и кладётся в `page_section.content`. Последующие
    не-заголовочные абзацы кладутся в `children` текущей LogicalSection
    (до следующего заголовка любого уровня). Если документ начинается
    с обычных абзацев — они идут прямо в `page_section.content`.
    """
    current_section: LogicalSection | None = None
    heading_counter = 0
    para_counter = 0

    for p in docx_doc.paragraphs:
        heading_level = _heading_level(p)
        if heading_level is not None:
            heading_counter += 1
            section = LogicalSection(
                id=f"sec-{heading_counter}",
                level=heading_level,
                heading=[TextRun(text=p.text)],
            )
            page_section.content.append(section)
            current_section = section
            continue

        para_counter += 1
        paragraph = _build_paragraph(p, idx=para_counter)
        if current_section is not None:
            current_section.children.append(paragraph)
        else:
            page_section.content.append(paragraph)


def _heading_level(p: DocxParagraph) -> int | None:
    """Вернуть уровень заголовка (1..9), если стиль — Heading N, иначе None."""
    style = p.style
    if style is None or style.name is None:
        return None
    m = _HEADING_RE.match(style.name)
    if not m:
        return None
    return int(m.group(1))


def _build_paragraph(p: DocxParagraph, *, idx: int) -> Paragraph:
    """Сконвертировать docx-параграф в модель Paragraph."""
    style_name = p.style.name if p.style is not None else None
    pf = p.paragraph_format
    alignment = _alignment_to_literal(pf.alignment)
    line_spacing = _line_spacing_value(pf.line_spacing)
    indent_cm = _indent_cm(pf.first_line_indent)

    content: list[InlineElement] = []
    style_font_name = _style_font_name(p)
    style_font_size_pt = _style_font_size_pt(p)

    for run in p.runs:
        text = run.text or ""
        font_name = run.font.name or style_font_name
        size_pt: float | None = (
            float(run.font.size.pt) if run.font.size is not None else style_font_size_pt
        )
        content.append(
            TextRun(
                text=text,
                bold=bool(run.bold) if run.bold is not None else None,
                italic=bool(run.italic) if run.italic is not None else None,
                font=font_name,
                size_pt=size_pt,
            )
        )

    return Paragraph(
        id=f"p-{idx}",
        content=content,
        style_name=style_name,
        alignment=alignment,
        line_spacing=line_spacing,
        first_line_indent_cm=indent_cm,
    )


def _alignment_to_literal(value: object | None) -> ParagraphAlignment | None:
    """WD_ALIGN_PARAGRAPH → литералка ParagraphAlignment."""
    if value is None:
        return None
    try:
        return _ALIGN_MAP.get(int(cast(Any, value)))
    except (TypeError, ValueError):
        return None


def _line_spacing_value(value: object | None) -> float | None:
    """Привести line_spacing к float (множитель) или None."""
    if value is None:
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _indent_cm(value: object | None) -> float | None:
    """Перевести first_line_indent в сантиметры."""
    if value is None:
        return None
    cm = getattr(value, "cm", None)
    if cm is None:
        return None
    return round(float(cm), 2)


def _style_font_name(p: DocxParagraph) -> str | None:
    """Имя шрифта, заданное на стиле абзаца (с обходом цепочки наследования стилей)."""
    style = p.style
    while style is not None:
        name = style.font.name if style.font is not None else None
        if name:
            return str(name)
        style = getattr(style, "base_style", None)
    return None


def _style_font_size_pt(p: DocxParagraph) -> float | None:
    """Размер шрифта (в пунктах) из стиля абзаца."""
    style = p.style
    while style is not None:
        size = style.font.size if style.font is not None else None
        if size is not None:
            return float(size.pt)
        style = getattr(style, "base_style", None)
    return None
