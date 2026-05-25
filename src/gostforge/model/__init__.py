"""Внутренняя модель документа.

Это сердце системы: и парсер, и валидатор, и экспортёр работают через эту
модель. Никаких ссылок на Word/OOXML здесь быть не должно — модель полностью
независима от формата хранения.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


SCHEMA_VERSION = "0.1.0"


# --- Inline content -----------------------------------------------------------


@dataclass
class TextRun:
    """Фрагмент текста с inline-разметкой."""

    text: str
    bold: bool = False
    italic: bool = False
    superscript: bool = False
    subscript: bool = False


@dataclass
class CrossRef:
    """Перекрёстная ссылка на другой элемент модели (рисунок, таблицу, формулу, источник)."""

    target_id: str
    display_template: str = "{kind} {num}"  # на экспорте: "рисунок 3", "таблица 1.2"


InlineElement = TextRun | CrossRef


# --- Блоки --------------------------------------------------------------------


class BlockType(str, Enum):
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    LIST = "list"
    CODE = "code"
    FOOTNOTE = "footnote"


@dataclass
class Block:
    """Базовый класс для контентных блоков. Не используется напрямую."""

    id: str
    type: BlockType


@dataclass
class Paragraph(Block):
    type: BlockType = BlockType.PARAGRAPH
    content: list[InlineElement] = field(default_factory=list)


@dataclass
class Figure(Block):
    type: BlockType = BlockType.FIGURE
    image_path: str = ""
    caption: list[InlineElement] = field(default_factory=list)
    number: int | None = None  # проставляется на экспорте


@dataclass
class Table(Block):
    type: BlockType = BlockType.TABLE
    caption: list[InlineElement] = field(default_factory=list)
    headers: list[list[InlineElement]] = field(default_factory=list)
    rows: list[list[list[InlineElement]]] = field(default_factory=list)
    column_widths_pct: list[float] | None = None
    number: int | None = None


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


# --- Логические разделы -------------------------------------------------------


@dataclass
class LogicalSection:
    """Раздел работы по содержанию (введение, глава 1, заключение)."""

    id: str
    heading: list[InlineElement] = field(default_factory=list)
    level: int = 1  # 1..4
    auto_numbering: bool = True
    children: list[LogicalSection | Block] = field(default_factory=list)


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
    work_type: Literal["coursework", "bachelor_thesis", "master_thesis", "research_report", "other"] = "other"


@dataclass
class Document:
    """Корень модели документа."""

    schema_version: str = SCHEMA_VERSION
    profile_id: str = "gost-7.32-2017"
    profile_version: str = "1.0"
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    page_sections: list[PageSection] = field(default_factory=list)
    bibliography: list[BibliographyEntry] = field(default_factory=list)
    abbreviations: dict[str, str] = field(default_factory=dict)
