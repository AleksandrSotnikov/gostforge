"""Внутренняя модель документа.

Это сердце системы: и парсер, и валидатор, и экспортёр работают через эту
модель. Никаких ссылок на Word/OOXML здесь быть не должно — модель полностью
независима от формата хранения.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

SCHEMA_VERSION = "0.4.0"


# --- Inline content -----------------------------------------------------------


@dataclass
class TextRun:
    """Фрагмент текста с inline-разметкой.

    Все атрибуты форматирования (`bold`, `italic`, `underline`,
    `superscript`, `subscript`, `font`, `size_pt`, `color_hex`) могут быть
    `None`, что означает «наследуется от стиля абзаца». Парсер выставляет
    только те значения, которые run задаёт явно. Проверки трактуют `None`
    как «нет нарушения».
    """

    text: str
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    font: str | None = None
    size_pt: float | None = None
    # Цвет в формате #RRGGBB. В обычном тексте проверка X.* запретит
    # непустой color_hex; используется для синтаксической подсветки
    # кода в BlockType.CODE.
    color_hex: str | None = None


@dataclass
class CrossRef:
    """Перекрёстная ссылка на другой элемент модели (рисунок, таблицу, формулу, источник)."""

    target_id: str
    display_template: str = "{kind} {num}"  # на экспорте: "рисунок 3", "таблица 1.2"
    # Текст «(см. ...)», «согласно ...» — добавляется перед автогенерируемой
    # ссылкой. None = только сам номер.
    prefix: str | None = None


@dataclass
class InlineFormula:
    """LaTeX-формула, отрисовываемая в потоке текста.

    На экспорте → OMML внутри run параграфа (а не отдельный <m:oMathPara>).
    На парсинге → распознаётся по <m:oMath>, лежащему внутри <w:r>.
    """

    latex: str
    # id опционален: inline-формулы обычно не нумеруются.
    id: str | None = None


@dataclass
class Citation:
    """Inline-цитата на источник из Document.bibliography.

    Отображается как «[N]» или «[N, с. P]» (по заданному template).
    Номер N вычисляется на экспорте из позиции источника в
    Document.bibliography (1-based).
    """

    source_id: str  # ссылка на BibliographyEntry.id
    pages: str | None = None  # "12", "12-15", "12, 17-20"
    template: str = "[{n}]"  # либо "[{n}, с. {pages}]"


@dataclass
class Hyperlink:
    """Гиперссылка на URL/email/якорь внутри документа.

    Отображается как кликабельный текст в Word/LibreOffice; на экспорте
    превращается в ``<w:hyperlink r:id="rIdN">`` + Relationship на URL
    (или ``<w:hyperlink w:anchor="bookmark">`` для внутренних).
    """

    url: str  # http://..., https://..., mailto:..., или пусто для anchor
    text: str  # отображаемый текст (то, что видит читатель)
    anchor: str | None = None  # для внутренних ссылок на bookmark


@dataclass
class FootnoteRef:
    """Ссылка на сноску из ``word/footnotes.xml``.

    Содержит id (стабильный в рамках одного документа) и опционально
    кэшированный текст самой сноски — для удобства проверок
    нормоконтроля без дополнительного lookup.
    """

    footnote_id: str
    text: str = ""  # содержимое сноски, заполняется парсером


InlineElement = TextRun | CrossRef | InlineFormula | Citation | Hyperlink | FootnoteRef


# --- Блоки --------------------------------------------------------------------


class BlockType(str, Enum):  # noqa: UP042  # str+Enum для JSON-сериализации (не StrEnum)
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    LIST = "list"
    CODE = "code"
    FOOTNOTE = "footnote"
    TOC = "toc"  # автоматическое оглавление через Word TOC-field


@dataclass
class Block:
    """Базовый класс для контентных блоков. Не используется напрямую."""

    id: str
    type: BlockType


ParagraphAlignment = Literal["left", "right", "center", "justify"]


@dataclass
class Paragraph(Block):
    type: BlockType = BlockType.PARAGRAPH
    content: list[InlineElement] = field(default_factory=list)
    # Имя Word-стиля (Normal, Heading 1, Caption, ...). Используется
    # парсером и проверками для классификации абзаца.
    style_name: str | None = None
    alignment: ParagraphAlignment | None = None
    line_spacing: float | None = None
    first_line_indent_cm: float | None = None
    # Принудительный разрыв страницы перед параграфом.
    # None — наследуется (значение не задано явно ни на параграфе, ни в стиле,
    # либо парсер не смог его установить).
    # True/False — задано явно (через w:pPr/w:pageBreakBefore у параграфа или
    # унаследовано от Word-стиля).
    page_break_before: bool | None = None
    # Интервалы перед/после абзаца в пунктах (w:spacing w:before/w:after).
    # None — атрибут не задан явно (наследуется от стиля). Используется
    # проверкой T.14 для контроля «лишнего» интервала между абзацами.
    space_before_pt: float | None = None
    space_after_pt: float | None = None


@dataclass
class Figure(Block):
    type: BlockType = BlockType.FIGURE
    image_path: str = ""
    caption: list[InlineElement] = field(default_factory=list)
    number: int | None = None  # проставляется на экспорте
    # Выравнивание параграфа, содержащего рисунок (заполняется парсером).
    # None — не задано / наследуется от стиля.
    alignment: Literal["left", "right", "center", "justify"] | None = None
    # DPI извлекается парсером из media-file через Pillow. None = не определено.
    dpi: int | None = None


@dataclass
class CellMerge:
    """Описание объединённой ячейки в таблице.

    Координаты row/col отсчитываются от 0; row=0 — шапка (headers),
    row=1+ — обычные данные (rows[0] = row=1 и т. д.).

    rowspan/colspan ≥ 1. При rowspan=2, colspan=1 это «вертикальное
    объединение двух ячеек одной колонки» (`<w:vMerge>`); colspan=2
    — горизонтальное (`<w:gridSpan w:val="2"/>`).
    """

    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1


@dataclass
class Table(Block):
    type: BlockType = BlockType.TABLE
    caption: list[InlineElement] = field(default_factory=list)
    headers: list[list[InlineElement]] = field(default_factory=list)
    # Дополнительные строки шапки НАД основной (`headers`). Пустой
    # список = одноуровневая шапка (поведение по умолчанию). Полезно для
    # таблиц с многоуровневыми заголовками типа «Группа 1 | Группа 2»
    # сверху и «Подзаг A | Подзаг B | ...» снизу.
    # Порядок — сверху вниз: extra_header_rows[0] — самая верхняя строка,
    # extra_header_rows[-1] непосредственно над headers. Колонки внутри
    # ряда часто склеиваются через `merges` (CellMerge с colspan).
    extra_header_rows: list[list[list[InlineElement]]] = field(default_factory=list)
    rows: list[list[list[InlineElement]]] = field(default_factory=list)
    column_widths_pct: list[float] | None = None
    number: int | None = None
    # Объединённые ячейки. Пустой список = плоская таблица.
    # Заполняется парсером из <w:vMerge>/<w:gridSpan>; экспортёр пишет
    # обратно. Координаты row/col — индексы в (extra_header_rows +
    # headers + rows), 0-based.
    merges: list[CellMerge] = field(default_factory=list)


@dataclass
class Formula(Block):
    type: BlockType = BlockType.FORMULA
    latex: str = ""
    number: int | None = None  # None = ненумерованная


@dataclass
class ListBlock(Block):
    type: BlockType = BlockType.LIST
    ordered: bool = False
    items: list[list[InlineElement]] = field(default_factory=list)
    # Уровень вложенности каждого элемента (0..8). По умолчанию пустой
    # список = все элементы на уровне 0 (плоский список — backwards
    # compatible со старым кодом). При item_levels[i] > 0 экспортёр
    # пишет multilevel abstractNum в numbering.xml с правильным ilvl,
    # парсер читает ilvl из <w:numPr><w:ilvl/> обратно.
    item_levels: list[int] = field(default_factory=list)


@dataclass
class TableOfContents(Block):
    """Автоматическое оглавление документа.

    Реализуется через Word TOC-field (``<w:fldSimple w:instr="TOC..."/>``):
    Word/LibreOffice сами строят список заголовков с номерами страниц
    при открытии файла (пользователь видит «обновить оглавление» при
    F9). Содержимое блока в .docx — пустой placeholder; настоящий
    список заголовков формируется приложением при рендере.
    """

    type: BlockType = BlockType.TOC
    # Уровни заголовков, которые включаются в TOC. Default 1-3 —
    # стандартное оглавление с главами, подразделами и пунктами.
    min_level: int = 1
    max_level: int = 3


# --- Логические разделы -------------------------------------------------------


@dataclass
class LogicalSection:
    """Раздел работы по содержанию (введение, глава 1, заключение).

    `disabled_checks` — список кодов проверок, которые НЕ должны
    применяться к содержимому этой секции (и её дочерних узлов).
    Спецзначение ``["*"]`` отключает ВСЕ проверки для раздела целиком.
    Это нужно для титульного листа, реферата, приложений — частей
    работы, которые оформляются по своим правилам (или вовсе по
    шаблону кафедры), а не по правилам, заданным в профиле.

    Поле — фича конструктора (builder), не сохраняется в .docx и не
    читается из .docx; при нормоконтроле чужих работ оно всегда
    пустое.
    """

    id: str
    heading: list[InlineElement] = field(default_factory=list)
    level: int = 1  # 1..4
    auto_numbering: bool = True
    children: list[LogicalSection | Block] = field(default_factory=list)
    disabled_checks: list[str] = field(default_factory=list)


# --- Секции вёрстки -----------------------------------------------------------


PageSectionType = Literal["title", "frontmatter", "main", "appendix", "custom"]


@dataclass
class PageGeometry:
    paper: str = "A4"
    margins_mm: dict[str, float] = field(
        default_factory=lambda: {"top": 20, "right": 15, "bottom": 20, "left": 30}
    )
    orientation: Literal["portrait", "landscape"] = "portrait"


@dataclass
class ContentTemplate:
    """Содержимое колонтитула с поддержкой плейсхолдеров."""

    left: list[InlineElement] | None = None
    center: list[InlineElement] | None = None
    right: list[InlineElement] | None = None


@dataclass
class HeaderConfig:
    default: ContentTemplate = field(default_factory=ContentTemplate)
    first_page: ContentTemplate | None = None
    even_page: ContentTemplate | None = None


@dataclass
class PageNumberingConfig:
    visible: bool = True
    format: Literal["arabic", "roman", "uppercase_letter"] = "arabic"
    start_mode: Literal["continue", "restart", "start_at"] = "continue"
    start_value: int | None = None


@dataclass
class PageSection:
    """Секция вёрстки с собственными колонтитулами и геометрией."""

    id: str
    name: str
    type: PageSectionType
    page: PageGeometry = field(default_factory=PageGeometry)
    header: HeaderConfig | None = None
    footer: HeaderConfig | None = None
    page_numbering: PageNumberingConfig = field(default_factory=PageNumberingConfig)
    link_to_previous: bool = False
    different_first_page: bool = False
    different_odd_even: bool = False
    content: list[LogicalSection | Block] = field(default_factory=list)


# --- Список литературы --------------------------------------------------------


@dataclass
class BibliographyEntry:
    id: str
    type: Literal["book", "article", "web", "standard", "thesis", "conference", "law"]
    fields: dict[str, str] = field(default_factory=dict)  # автор, заглавие, год, ...


# --- Корень модели ------------------------------------------------------------


@dataclass
class DocumentMetadata:
    title: str = ""
    author: str = ""
    supervisor: str = ""
    organization: str = ""
    department: str = ""
    year: int | None = None
    work_type: Literal[
        "coursework", "bachelor_thesis", "master_thesis", "research_report", "other"
    ] = "other"


@dataclass
class Comment:
    """Комментарий рецензента из word/comments.xml.

    Word/LibreOffice кладут комментарии в отдельный XML-part:
    каждый ``<w:comment>`` имеет id, автора, дату и тело
    (один или несколько параграфов). В document.xml — только
    ссылки ``<w:commentRangeStart>``, ``<w:commentRangeEnd>``,
    ``<w:commentReference>`` с тем же id.

    Парсер собирает list[Comment] в Document.comments. Это полезно
    для научного руководителя, оставляющего заметки прямо в Word,
    и для UI, который может показать их в редакторе.
    """

    id: str
    author: str = ""
    date: str = ""  # ISO 8601, как в XML; парсить дальше пользователю
    text: str = ""
    # Контекст: id раздела, к которому привязан комментарий (если удалось
    # вычислить через commentRangeStart). None = верхнеуровневый или
    # не определено.
    section_id: str | None = None


@dataclass
class Document:
    """Корень модели документа."""

    schema_version: str = SCHEMA_VERSION
    profile_id: str = "gost-7.32-2017"
    profile_version: str = "1.0"
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    page_sections: list[PageSection] = field(default_factory=list)
    bibliography: list[BibliographyEntry] = field(default_factory=list)
    # Глобальные настройки документа из word/settings.xml.
    # None — не задано (наследуется от приложения).
    auto_hyphenation: bool | None = None
    abbreviations: dict[str, str] = field(default_factory=dict)
    # Комментарии рецензента из word/comments.xml. Заполняется парсером.
    comments: list[Comment] = field(default_factory=list)
