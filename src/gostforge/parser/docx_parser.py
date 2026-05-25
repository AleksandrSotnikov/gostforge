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

# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import docx  # type: ignore[import-not-found]
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore[import-not-found]
from docx.table import Table as DocxTableCls  # type: ignore[import-not-found]
from docx.text.paragraph import Paragraph as DocxParagraphCls  # type: ignore[import-not-found]
from lxml import etree  # type: ignore[import-untyped]

from gostforge.model import (
    BibliographyEntry,
    Block,
    ContentTemplate,
    Document,
    DocumentMetadata,
    Figure,
    Formula,
    HeaderConfig,
    InlineElement,
    ListBlock,
    LogicalSection,
    PageGeometry,
    PageSection,
    Paragraph,
    ParagraphAlignment,
    Table,
    TextRun,
)

if TYPE_CHECKING:
    DocxDocument = Any
    DocxSection = Any
    DocxParagraph = Any
    DocxTable = Any
    DocxCell = Any


# Пространство имён OOXML wordprocessingml
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NSMAP = {"w": W_NS, "m": M_NS}

# Шаблон номера формулы в скобках в конце текста параграфа: «(3)» или «(3.1)».
_FORMULA_NUMBER_RE = re.compile(r"\((\d+(?:\.\d+)?)\)\s*$")

# Соответствие WD_ALIGN_PARAGRAPH → строковая литералка модели
_ALIGN_MAP: dict[int, ParagraphAlignment] = {
    int(WD_ALIGN_PARAGRAPH.LEFT): "left",
    int(WD_ALIGN_PARAGRAPH.RIGHT): "right",
    int(WD_ALIGN_PARAGRAPH.CENTER): "center",
    int(WD_ALIGN_PARAGRAPH.JUSTIFY): "justify",
}

# Регэксп заголовков Word: "Heading 1", "Heading 2" и т.д.
_HEADING_RE = re.compile(r"^Heading\s+(\d+)$")

# Шаблоны подписей по тексту: «Рисунок 1 — ...», «Рис. 1 ...»; «Таблица 1 — ...».
_FIGURE_CAPTION_TEXT_RE = re.compile(r"^Рис(?:унок)?\.?\s+\d")
_TABLE_CAPTION_TEXT_RE = re.compile(r"^Таблица\s+\d")

# Множество имён Word-стилей подписи (нормализуется в lowercase).
_CAPTION_STYLE_NAMES = {"caption", "image caption", "figure caption", "table caption"}

# Заголовки, признаваемые началом раздела со списком литературы (нормализация
# к нижнему регистру и сжатию пробелов выполняется отдельно).
_BIBLIOGRAPHY_HEADINGS: set[str] = {
    "список использованных источников",
    "список литературы",
    "библиографический список",
    "список источников",
}

# Эвристики определения типа библиографической записи.
_BIB_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_BIB_STANDARD_RE = re.compile(r"\bГОСТ\b")
_BIB_ARTICLE_RE = re.compile(r"(?:^|\s)//\s|\bЖурнал\b|журн\.|\bNo\.|№")
_BIB_THESIS_RE = re.compile(r"\bдис\.|\bдиссертация\b|\bавтореф\.", re.IGNORECASE)
_BIB_CONFERENCE_RE = re.compile(r"\bконференция\b|\bматериалы\b|\bсб\.\s*ст\.", re.IGNORECASE)
_BIB_LAW_RE = re.compile(
    r"\bзакон\b|\bфедер\.\s*закон\b|\bпостановление\b", re.IGNORECASE
)


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
    bibliography = _extract_bibliography([page_section])
    auto_hyphenation = _extract_auto_hyphenation(docx_doc)
    _populate_image_dpi(docx_doc, page_section)

    return Document(
        metadata=metadata,
        page_sections=[page_section],
        bibliography=bibliography,
        auto_hyphenation=auto_hyphenation,
    )


def _populate_image_dpi(docx_doc: DocxDocument, page_section: PageSection) -> None:
    """Для каждой Figure с image_path вида 'embedded:rIdN' извлечь DPI.

    Использует Pillow для определения разрешения media-file. Если Pillow
    недоступен, оставляет dpi=None. DPI вычисляется как min(x_dpi, y_dpi)
    из info['dpi'] или из физических размеров EMU vs пикселей (упрощённо —
    только info['dpi']).
    """
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return

    def _iter_figures(items: list[LogicalSection | Block]) -> list[Figure]:
        out: list[Figure] = []
        for item in items:
            if isinstance(item, Figure):
                out.append(item)
            elif isinstance(item, LogicalSection):
                out.extend(_iter_figures(item.children))
        return out

    figures = _iter_figures(page_section.content)
    for fig in figures:
        if not fig.image_path.startswith("embedded:"):
            continue
        rid = fig.image_path[len("embedded:"):]
        try:
            image_part = docx_doc.part.related_parts.get(rid)
            if image_part is None:
                continue
            blob = image_part.blob
            with Image.open(__import__("io").BytesIO(blob)) as im:
                dpi_value = im.info.get("dpi")
                if dpi_value:
                    fig.dpi = int(min(dpi_value))
        except Exception:  # noqa: BLE001 — повреждённый media-file не должен валить парсер
            continue


def _extract_auto_hyphenation(docx_doc: DocxDocument) -> bool | None:
    """Прочитать `<w:autoHyphenation/>` из word/settings.xml.

    По OOXML autoHyphenation — toggle-элемент: его наличие включает
    автоматический перенос. Отсутствие = выключен. На Фазе 1
    интерпретируем строго: элемент найден → True, иначе False.
    """
    try:
        settings_part = docx_doc.part.package.part_related_by(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings"
        )
    except Exception:  # noqa: BLE001 — settings.xml не обязательная часть
        return None
    settings_xml = settings_part.blob
    try:
        root = etree.fromstring(settings_xml)
    except Exception:  # noqa: BLE001
        return None
    auto_hyph = root.find(f"{{{W_NS}}}autoHyphenation")
    if auto_hyph is None:
        return False
    val = auto_hyph.get(f"{{{W_NS}}}val")
    # По OOXML toggle: отсутствие val или val="1"/"true" → on; "0"/"false" → off.
    if val in {"0", "false"}:
        return False
    return True


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

    paper = _detect_paper_size(sect)
    orientation = _detect_orientation(sect)

    page_section = PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page=PageGeometry(margins_mm=margins_mm, paper=paper, orientation=orientation),
    )

    # Стартовая страница нумерации: <w:pgNumType w:start="N"/> в sectPr.
    # Если атрибут задан — это эквивалентно start_mode = "start_at".
    start_value = _extract_page_number_start(sect)
    if start_value is not None:
        page_section.page_numbering.start_mode = "start_at"
        page_section.page_numbering.start_value = start_value

    # Формат нумерации: <w:pgNumType w:fmt="decimal|upperRoman|..."/>.
    fmt = _extract_page_number_format(sect)
    if fmt is not None:
        page_section.page_numbering.format = fmt

    footer_config = _extract_footer(sect)
    if footer_config is not None:
        page_section.footer = footer_config
        page_section.page_numbering.visible = True

    header_config = _extract_header(sect)
    if header_config is not None:
        page_section.header = header_config
        # Если PAGE-поле было в шапке, тоже считаем нумерацию видимой
        if _template_has_text(header_config.default, "{page}"):
            page_section.page_numbering.visible = True

    return page_section


def _template_has_text(template: ContentTemplate | None, needle: str) -> bool:
    """Проверка: есть ли в каком-либо слоте шаблона текст `needle`."""
    if template is None:
        return False
    for slot in (template.left, template.center, template.right):
        if slot is None:
            continue
        for el in slot:
            if isinstance(el, TextRun) and needle in el.text:
                return True
    return False


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


# OOXML поддерживает много форматов (decimalZero, hindiNumbers, и т.д.),
# но в модели мы фиксируем только три обиходных. Остальные значения
# отображаем в ближайший аналог (decimal → arabic, прочие — None).
_PAGE_FMT_MAP: dict[str, Literal["arabic", "roman", "uppercase_letter"]] = {
    "decimal": "arabic",
    "decimalZero": "arabic",
    "lowerRoman": "roman",
    "upperRoman": "roman",
    "lowerLetter": "uppercase_letter",
    "upperLetter": "uppercase_letter",
}


def _extract_page_number_format(
    sect: DocxSection,
) -> Literal["arabic", "roman", "uppercase_letter"] | None:
    """Прочитать <w:pgNumType w:fmt="..."/> и вернуть значение для модели.

    Возвращает None, если элемент или атрибут отсутствуют, либо если
    OOXML-значение не покрывается моделью.
    """
    sect_pr = getattr(sect, "_sectPr", None)
    if sect_pr is None:
        return None
    pg_num_type = sect_pr.find(f"{{{W_NS}}}pgNumType")
    if pg_num_type is None:
        return None
    fmt_attr = pg_num_type.get(f"{{{W_NS}}}fmt")
    if fmt_attr is None:
        return None
    return _PAGE_FMT_MAP.get(fmt_attr)



def _length_to_mm(length: object | None) -> float:
    """Перевести python-docx Length в миллиметры (округление до 0.1 мм)."""
    if length is None:
        # Дефолты Word подставит сам python-docx; если значение отсутствует
        # после чтения секции — возвращаем 0.0, чтобы валидатор увидел это.
        return 0.0
    mm = float(length.mm)  # type: ignore[attr-defined]
    return round(mm, 1)


# Известные размеры бумаги в мм. Сравнение с допуском ±2 мм.
_PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A5": (148.0, 210.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}


def _detect_paper_size(sect: DocxSection) -> str:
    """Определить формат бумаги по page_width/page_height.

    Сравнивает с известными размерами (A4, A3, ...) с допуском ±2 мм.
    Если ничего не подошло — возвращает «Unknown».
    """
    width_mm = _length_to_mm(sect.page_width)
    height_mm = _length_to_mm(sect.page_height)
    # Нормализуем (короткая сторона — первая), чтобы сравнение не зависело от ориентации
    short, long = sorted((width_mm, height_mm))
    for name, (w, h) in _PAPER_SIZES_MM.items():
        if abs(short - w) <= 2.0 and abs(long - h) <= 2.0:
            return name
    return "Unknown"


def _detect_orientation(sect: DocxSection) -> Literal["portrait", "landscape"]:
    """Определить ориентацию страницы по соотношению ширина/высота.

    Если width > height → landscape, иначе portrait. Атрибут sect.orientation
    бывает None для дефолтных значений, поэтому считаем по фактическим
    размерам через _length_to_mm.
    """
    width_mm = _length_to_mm(sect.page_width)
    height_mm = _length_to_mm(sect.page_height)
    if width_mm > height_mm:
        return "landscape"
    return "portrait"


def _extract_footer(sect: DocxSection) -> HeaderConfig | None:
    """Прочитать footer секции и собрать HeaderConfig, если есть поле PAGE."""
    return _extract_header_or_footer(sect.footer)


def _extract_header(sect: DocxSection) -> HeaderConfig | None:
    """Прочитать header секции и собрать HeaderConfig, если есть поле PAGE.

    Симметрично _extract_footer. Поле PAGE в header — это альтернатива
    положению номера страницы (top_*); проверка F.04 такие случаи
    обрабатывает.
    """
    return _extract_header_or_footer(sect.header)


def _extract_header_or_footer(container: Any) -> HeaderConfig | None:
    """Общая логика парсинга header/footer: ищем поле PAGE и кладём в подходящий слот."""
    if container is None:
        return None

    template = ContentTemplate()
    found = False

    for fp in container.paragraphs:
        if not _paragraph_has_page_field(fp):
            continue
        alignment = _alignment_to_literal(fp.paragraph_format.alignment)
        slot_runs = [TextRun(text="{page}")]
        # Распределение по слоту определяется выравниванием параграфа в
        # колонтитуле. None и justify трактуем как center — это типичный
        # случай отображения номера страницы.
        if alignment == "right":
            template.right = slot_runs
        elif alignment == "left":
            template.left = slot_runs
        else:
            template.center = slot_runs
        found = True
        # На Фазе 1 ограничиваемся одним маркером {page} в колонтитуле.
        break

    if not found:
        return None

    return HeaderConfig(default=template)


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


class _Counters:
    """Сквозные счётчики id блоков (общие на весь документ)."""

    def __init__(self) -> None:
        self.heading = 0
        self.paragraph = 0
        self.figure = 0
        self.table = 0
        self.list = 0
        self.formula = 0


# Имена Word-стилей, обозначающих элемент списка (case-insensitive).
_LIST_STYLE_PREFIXES = ("list paragraph", "list number", "list bullet", "list")


def _paragraph_list_kind(dp: DocxParagraph) -> str | None:
    """Определить, является ли параграф элементом списка.

    Возвращает 'ordered' | 'bulleted' | None. Эвристика:
    - <w:numPr> в <w:pPr> → есть привязка к списку Word. Тип определяется
      по стилю абзаца (List Number → ordered, List Bullet → bulleted),
      иначе по умолчанию ordered (Word обычно так).
    - Стиль абзаца начинается с 'List Number' → ordered.
    - Стиль абзаца начинается с 'List Bullet' → bulleted.
    - Иначе None — обычный параграф.
    """
    p_xml = dp._p
    num_pr = p_xml.find(f"{{{W_NS}}}pPr/{{{W_NS}}}numPr")
    style_name = (dp.style.name if dp.style is not None else "").lower()
    if style_name.startswith("list number"):
        return "ordered"
    if style_name.startswith("list bullet"):
        return "bulleted"
    if num_pr is not None:
        # Привязка к списку без указания типа в стиле — считаем ordered.
        return "ordered"
    return None


def _populate_content(docx_doc: DocxDocument, page_section: PageSection) -> None:
    """Пройти по телу документа в порядке появления и наполнить PageSection.

    Алгоритм Фазы 1:
    1. Итерируемся по `body.iterchildren()` и обрабатываем каждый элемент
       по тегу: `<w:p>` — параграф/заголовок/рисунок, `<w:tbl>` — таблица.
       `<w:sectPr>` и прочие служебные элементы — пропускаем.
    2. Заголовок (Heading N) открывает новую LogicalSection.
    3. Параграфы и таблицы кладутся либо в текущую LogicalSection, либо
       прямо в `page_section.content` (если ни одного раздела ещё не было).
    4. После того как линейная последовательность собрана, делается
       единый проход «склейки подписей»: рисункам подпись прикрепляется
       снизу, таблицам — сверху; параграфы-подписи удаляются.
    """
    current_section: LogicalSection | None = None
    counters = _Counters()
    body = docx_doc.element.body

    # Буфер для группировки последовательных list-параграфов в один ListBlock.
    list_buffer: list[tuple[str, list[InlineElement]]] = []  # (kind, content)

    def flush_list_buffer() -> None:
        """Если в буфере накопились list-параграфы — сделать из них ListBlock."""
        if not list_buffer:
            return
        # Тип ordered определяется по большинству элементов буфера
        ordered = sum(1 for k, _ in list_buffer if k == "ordered") >= len(list_buffer) / 2
        counters.list += 1
        list_block = ListBlock(
            id=f"list-{counters.list}",
            ordered=ordered,
            items=[content for _, content in list_buffer],
        )
        _append_block(list_block, page_section, current_section)
        list_buffer.clear()

    for child in body.iterchildren():
        tag = etree.QName(child.tag).localname
        if tag == "p":
            dp = DocxParagraphCls(child, docx_doc)
            heading_level = _heading_level(dp)
            if heading_level is not None:
                flush_list_buffer()
                counters.heading += 1
                section = LogicalSection(
                    id=f"sec-{counters.heading}",
                    level=heading_level,
                    heading=[TextRun(text=dp.text)],
                )
                page_section.content.append(section)
                current_section = section
                continue

            # Распознаём элемент списка ещё до построения Paragraph
            list_kind = _paragraph_list_kind(dp)
            if list_kind is not None:
                # Собираем inline-контент параграфа как InlineElement-список
                runs: list[InlineElement] = [
                    TextRun(text=run.text) for run in dp.runs if run.text
                ]
                if not runs and dp.text:
                    runs = [TextRun(text=dp.text)]
                if runs:
                    list_buffer.append((list_kind, runs))
                continue

            # Обычный параграф или figure — сначала закрываем накопленный список
            flush_list_buffer()
            block = _block_from_paragraph(dp, counters)
            _append_block(block, page_section, current_section)
        elif tag == "tbl":
            flush_list_buffer()
            counters.table += 1
            table = _build_table(DocxTableCls(child, docx_doc), idx=counters.table)
            _append_block(table, page_section, current_section)
        # sectPr и прочие — игнорируем.

    # Не забыть закрыть финальный список (если документ закончился им)
    flush_list_buffer()

    # Склейка подписей: для content страницы и для каждой LogicalSection.
    _glue_captions(page_section.content)
    for section in _iter_logical_sections(page_section.content):
        _glue_captions(section.children)


def _append_block(
    block: Block,
    page_section: PageSection,
    current_section: LogicalSection | None,
) -> None:
    """Положить блок в текущую LogicalSection либо прямо в content страницы."""
    if current_section is not None:
        current_section.children.append(block)
    else:
        page_section.content.append(block)


def _iter_logical_sections(
    items: list[LogicalSection | Block],
) -> list[LogicalSection]:
    """Рекурсивно собрать все LogicalSection (всех уровней) — для склейки."""
    result: list[LogicalSection] = []
    for item in items:
        if isinstance(item, LogicalSection):
            result.append(item)
            result.extend(_iter_logical_sections(item.children))
    return result


def _block_from_paragraph(dp: DocxParagraph, counters: _Counters) -> Block:
    """Конвертировать <w:p> в Figure / Formula / Paragraph.

    Приоритет распознавания:
    1. <w:drawing> → Figure (рисунок).
    2. <m:oMath> или <m:oMathPara> → Formula (формула).
    3. Иначе — обычный Paragraph.
    """
    drawings = dp._p.findall(f".//{{{W_NS}}}drawing")
    if drawings:
        counters.figure += 1
        image_path = _extract_drawing_rid(drawings[0])
        alignment = _alignment_to_literal(dp.paragraph_format.alignment)
        return Figure(
            id=f"fig-{counters.figure}",
            image_path=image_path,
            caption=[],
            alignment=alignment,
        )
    omml_text = _extract_omml_text(dp._p)
    if omml_text is not None:
        counters.formula += 1
        return Formula(
            id=f"formula-{counters.formula}",
            latex=omml_text,
            number=_extract_formula_number(dp),
        )
    counters.paragraph += 1
    return _build_paragraph(dp, idx=counters.paragraph)


def _extract_drawing_rid(drawing_elem: Any) -> str:
    """Извлечь relationship-id изображения из <w:drawing>.

    Внутри <w:drawing> есть <a:blip r:embed="rIdN"/> (или r:link для
    внешних ссылок). Возвращает идентификатор вида 'embedded:rIdN'.
    Если не нашли — пустую строку (тогда экспортёр напишет placeholder).
    """
    # Namespace для DrawingML и Relationships
    a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    for blip in drawing_elem.iter(f"{{{a_ns}}}blip"):
        embed = blip.get(f"{{{r_ns}}}embed")
        if embed:
            return f"embedded:{embed}"
        link = blip.get(f"{{{r_ns}}}link")
        if link:
            return f"linked:{link}"
    return ""


def _extract_omml_text(p_elem: Any) -> str | None:
    """Склейка `<m:t>` элементов из всех `<m:oMath>` в параграфе.

    Это не настоящий LaTeX — Фаза 1 ограничивается видимым математическим
    текстом (операнды и константы). Если ни одного `<m:oMath>` в параграфе
    нет, возвращаем None.
    """
    omath_elements = p_elem.findall(f".//{{{M_NS}}}oMath")
    if not omath_elements:
        return None
    parts: list[str] = []
    for omath in omath_elements:
        for t in omath.findall(f".//{{{M_NS}}}t"):
            if t.text:
                parts.append(t.text)
    return "".join(parts)


def _extract_formula_number(dp: DocxParagraph) -> int | None:
    """Извлечь номер формулы из паттерна «(N)» / «(N.M)» в конце параграфа."""
    text = dp.text or ""
    match = _FORMULA_NUMBER_RE.search(text)
    if match is None:
        return None
    raw = match.group(1).split(".")[0]
    try:
        return int(raw)
    except ValueError:
        return None


def _build_table(dtable: DocxTable, *, idx: int) -> Table:
    """Сконвертировать docx-таблицу в модель Table.

    Headers — первый ряд cells; rows — остальные ряды. Каждая ячейка
    хранится как list[InlineElement] из текста первого параграфа
    ячейки (без атрибутов форматирования — Фаза 1).
    """
    rows_raw = list(dtable.rows)
    headers: list[list[InlineElement]] = []
    body_rows: list[list[list[InlineElement]]] = []

    if rows_raw:
        headers = [_cell_inline(cell) for cell in rows_raw[0].cells]
        for row in rows_raw[1:]:
            body_rows.append([_cell_inline(cell) for cell in row.cells])

    return Table(
        id=f"t-{idx}",
        caption=[],
        headers=headers,
        rows=body_rows,
    )


def _cell_inline(cell: DocxCell) -> list[InlineElement]:
    """Извлечь inline-содержимое первого параграфа ячейки (только текст)."""
    paragraphs = cell.paragraphs
    if not paragraphs:
        return []
    text = paragraphs[0].text or ""
    if not text:
        return []
    return [TextRun(text=text)]


def _glue_captions(items: list[LogicalSection | Block]) -> None:
    """Эвристика склейки подписей.

    Один проход по списку блоков:
    - параграф-подпись СВЕРХУ присоединяется к следующей таблице;
    - параграф-подпись СНИЗУ присоединяется к предыдущему рисунку;
    - параграфы-подписи удаляются из списка.

    Параграф, ставший подписью таблицы, не должен также считаться
    подписью рисунка — поэтому таблица обрабатывается раньше рисунка
    при проверке предыдущего элемента в `result`.
    """
    if not items:
        return

    result: list[LogicalSection | Block] = []
    i = 0
    n = len(items)
    while i < n:
        item = items[i]
        if isinstance(item, Table):
            if result and isinstance(result[-1], Paragraph) and _is_table_caption(result[-1]):
                cap = result.pop()
                assert isinstance(cap, Paragraph)
                item.caption = list(cap.content)
            result.append(item)
            i += 1
            continue

        if isinstance(item, Figure):
            result.append(item)
            j = i + 1
            if j < n:
                nxt = items[j]
                if isinstance(nxt, Paragraph) and _is_figure_caption(nxt):
                    item.caption = list(nxt.content)
                    i = j + 1
                    continue
            i += 1
            continue

        result.append(item)
        i += 1

    items[:] = result


def _is_figure_caption(paragraph: Paragraph) -> bool:
    """Параграф похож на подпись рисунка: стиль Caption или текст «Рисунок N ...»."""
    if _has_caption_style(paragraph):
        return True
    text = _paragraph_plain_text(paragraph).strip()
    return bool(_FIGURE_CAPTION_TEXT_RE.match(text))


def _is_table_caption(paragraph: Paragraph) -> bool:
    """Параграф похож на подпись таблицы: стиль Caption или текст «Таблица N ...»."""
    if _has_caption_style(paragraph):
        return True
    text = _paragraph_plain_text(paragraph).strip()
    return bool(_TABLE_CAPTION_TEXT_RE.match(text))


def _has_caption_style(paragraph: Paragraph) -> bool:
    """Проверить, что style_name похож на «Caption» (с учётом регистра/вариантов)."""
    if paragraph.style_name is None:
        return False
    return paragraph.style_name.strip().lower() in _CAPTION_STYLE_NAMES


def _paragraph_plain_text(paragraph: Paragraph) -> str:
    """Склейка text всех TextRun параграфа."""
    return "".join(el.text for el in paragraph.content if isinstance(el, TextRun))


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
    page_break_before = _page_break_before(p)

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
        page_break_before=page_break_before,
    )


def _page_break_before(p: DocxParagraph) -> bool | None:
    """Узнать, выставлен ли у параграфа разрыв страницы перед ним.

    Проверяем сам параграф (w:pPr/w:pageBreakBefore) и цепочку стилей
    (Word-стили могут наследовать pageBreakBefore от base_style). Возвращаем:
      - True, если флаг найден явно;
      - None, если не найден ни на параграфе, ни в стиле (наследуется/
        не задан).

    Возможный False в текущей реализации не выдаём — w:pageBreakBefore
    в OOXML по умолчанию означает True; снятие флага через `w:val="0"`
    встречается редко, но мы его учитываем.
    """
    # 1) Прямое свойство параграфа: w:pPr/w:pageBreakBefore
    direct = _paragraph_break_flag(p._p)
    if direct is not None:
        return direct

    # 2) Свойство, унаследованное от стиля абзаца (с обходом base_style)
    style = p.style
    while style is not None:
        style_element = getattr(style, "element", None)
        if style_element is not None:
            inherited = _style_break_flag(style_element)
            if inherited is not None:
                return inherited
        style = getattr(style, "base_style", None)
    return None


def _paragraph_break_flag(p_elem: object) -> bool | None:
    """Найти w:pageBreakBefore в w:pPr заданного <w:p>."""
    p_pr = p_elem.find(f"{{{W_NS}}}pPr")  # type: ignore[attr-defined]
    if p_pr is None:
        return None
    return _read_break_flag(p_pr)


def _style_break_flag(style_elem: object) -> bool | None:
    """Найти w:pageBreakBefore в w:pPr стилей (<w:style>/<w:docDefaults>)."""
    p_pr = style_elem.find(f"{{{W_NS}}}pPr")  # type: ignore[attr-defined]
    if p_pr is None:
        return None
    return _read_break_flag(p_pr)


def _read_break_flag(p_pr_elem: object) -> bool | None:
    """Прочитать <w:pageBreakBefore> внутри <w:pPr>.

    OOXML toggle-семантика: элемент без атрибута w:val или со значением
    "true"/"1"/"on" — True; "false"/"0"/"off" — False; отсутствие
    элемента — None.
    """
    elem = p_pr_elem.find(f"{{{W_NS}}}pageBreakBefore")  # type: ignore[attr-defined]
    if elem is None:
        return None
    val = elem.get(f"{{{W_NS}}}val")
    if val is None:
        return True
    return val.lower() not in {"false", "0", "off"}


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


# --- список литературы --------------------------------------------------------


def _extract_bibliography(page_sections: list[PageSection]) -> list[BibliographyEntry]:
    """Найти раздел со списком литературы и собрать записи в плоский список.

    Алгоритм:
    1. Перебираем все LogicalSection уровня 1 во всех PageSection.
    2. Сравниваем нормализованный текст заголовка со списком известных
       названий раздела (`_BIBLIOGRAPHY_HEADINGS`).
    3. Каждый прямой дочерний Paragraph такой секции, текст которого
       непустой после strip, превращаем в `BibliographyEntry` с id вида
       `ref-{idx}`, где idx — сквозной счётчик по всем найденным записям.
    4. Тип записи определяется эвристически по содержимому текста.
    5. `fields["raw"]` — полный текст параграфа (минимум для Фазы 1).

    Пустые параграфы пропускаются. Параграфы из раздела остаются на месте
    в `LogicalSection.children` — модель сознательно дублирует данные
    в `Document.bibliography`, чтобы валидаторы могли работать как по
    плоскому списку, так и по содержанию страницы.
    """
    entries: list[BibliographyEntry] = []
    idx = 0
    for ps in page_sections:
        for section in _iter_logical_sections(ps.content):
            if section.level != 1:
                continue
            heading_text = _normalize_heading(section.heading)
            if heading_text not in _BIBLIOGRAPHY_HEADINGS:
                continue
            for child in section.children:
                if not isinstance(child, Paragraph):
                    continue
                raw = _paragraph_plain_text(child).strip()
                if not raw:
                    continue
                idx += 1
                entries.append(
                    BibliographyEntry(
                        id=f"ref-{idx}",
                        type=_detect_bibliography_type(raw),
                        fields={"raw": raw},
                    )
                )
    return entries


def _normalize_heading(content: Sequence[InlineElement]) -> str:
    """Привести inline-заголовок к строке без регистра и лишних пробелов."""
    text = "".join(el.text for el in content if isinstance(el, TextRun))
    return " ".join(text.lower().split())


def _detect_bibliography_type(
    raw: str,
) -> Literal["book", "article", "web", "standard", "thesis", "conference", "law"]:
    """Эвристически определить тип библиографической записи по её тексту."""
    if _BIB_URL_RE.search(raw):
        return "web"
    if _BIB_STANDARD_RE.search(raw) or raw.startswith("ГОСТ "):
        return "standard"
    if _BIB_THESIS_RE.search(raw):
        return "thesis"
    if _BIB_CONFERENCE_RE.search(raw):
        return "conference"
    if _BIB_LAW_RE.search(raw):
        return "law"
    if _BIB_ARTICLE_RE.search(raw):
        return "article"
    return "book"
