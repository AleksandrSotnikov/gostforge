"""B.* — проверки таблиц."""

from __future__ import annotations

import re
from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    InlineElement,
    LogicalSection,
    PageSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# Формат подписи таблицы по ГОСТ 7.32-2017: «Таблица N — Название».
_TABLE_CAPTION_RE = re.compile(r"^Таблица\s+\d+(?:\.\d+)?\s+[—–-]\s+\S")

# Альтернативный вариант: «Таблица 1. Название».
_TABLE_CAPTION_DOT_RE = re.compile(r"^Таблица\s+\d+(?:\.\d+)?\.\s+\S")


def _iter_tables(items: Sequence[LogicalSection | Block]) -> list[Table]:
    """Рекурсивно собрать все Table из content (через LogicalSection.children)."""
    result: list[Table] = []
    for item in items:
        if isinstance(item, Table):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_tables(item.children))
    return result


def _all_tables(document: Document) -> list[tuple[PageSection, Table]]:
    """Все Table документа — со ссылкой на PageSection (для location)."""
    result: list[tuple[PageSection, Table]] = []
    for ps in document.page_sections:
        for table in _iter_tables(ps.content):
            result.append((ps, table))
    return result


def _has_text(elements: Sequence[InlineElement]) -> bool:
    """True, если в списке есть хотя бы один TextRun с непустым текстом."""
    return any(isinstance(el, TextRun) and el.text and el.text.strip() for el in elements)


@register("B.02")
def check_table_caption_above(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Подпись таблицы должна располагаться над таблицей (заглушка Фазы 2).

    На Фазе 2 модель не сохраняет caption_position у Table: парсер делает
    склейку и кладёт подпись сверху, если она была найдена выше таблицы.
    Если caption присутствует — он уже «над таблицей». Если caption пуст —
    это случай B.01, дублировать не нужно.

    Когда парсер начнёт сохранять caption_position явно, здесь появится
    логика: caption_position != "above" → Violation.
    """
    return []


@register("B.04")
def check_table_continuation_header(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """При переносе таблицы на новую страницу должен быть заголовок «Продолжение таблицы N» (заглушка Фазы 2).

    На Фазе 2 — заглушка: парсер не сохраняет разбивку на страницы, без
    рендеринга это нельзя проверить. Когда появится модель страниц
    (PageBreak/PageLayout), здесь будет проверка наличия заголовка
    «Продолжение таблицы N» на каждой странице, куда переносится таблица.
    """
    return []


@register("B.05")
def check_table_header_repeats(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Шапка таблицы должна повторяться при переносе на новую страницу (заглушка Фазы 2).

    В docx это атрибут `<w:tblHeader/>` у первой строки таблицы. Парсер
    на Фазе 2 не сохраняет это в модели Table. Когда модель таблицы
    получит поле `header_repeats: bool`, здесь появится проверка: если
    таблица потенциально занимает больше страницы и header_repeats != True
    — Violation.
    """
    return []


@register("B.01")
def check_table_has_caption(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая таблица должна иметь подпись «Таблица N — Название»."""
    violations: list[Violation] = []
    for page_section, table in _all_tables(document):
        if _has_text(table.caption):
            continue
        violations.append(
            Violation(
                check_code="B.01",
                severity="error",
                message=f"У таблицы «{table.id}» отсутствует подпись",
                location=f"page_sections.{page_section.id}.table[{table.id}]",
                suggestion="Добавить над таблицей подпись в формате «Таблица N — Название»",
                details={"table_id": table.id},
            )
        )
    return violations


def _caption_text(elements: Sequence[InlineElement]) -> str:
    """Склеить подпись таблицы в строку (только TextRun)."""
    return "".join(el.text for el in elements if isinstance(el, TextRun)).strip()


@register("B.03")
def check_table_caption_format(document: Document, profile: Profile) -> list[Violation]:
    """Подпись таблицы должна быть в формате «Таблица N — Название».

    Параметры:
    - `allow_dot_after_number` (bool, default False): если True, также
      принимается «Таблица 1. Название».

    Пустые подписи не проверяются — это случай B.01.
    """
    violations: list[Violation] = []
    config = profile.checks.get("B.03")
    allow_dot = False
    if config and config.params.get("allow_dot_after_number") is not None:
        allow_dot = bool(config.params["allow_dot_after_number"])

    for page_section, table in _all_tables(document):
        text = _caption_text(table.caption)
        if not text:
            # Пустая подпись — это B.01, не дублируем.
            continue
        if _TABLE_CAPTION_RE.match(text):
            continue
        if allow_dot and _TABLE_CAPTION_DOT_RE.match(text):
            continue
        violations.append(
            Violation(
                check_code="B.03",
                severity="error",
                message=(
                    f"Подпись таблицы «{text}» не соответствует формату «Таблица N — Название»"
                ),
                location=f"page_sections.{page_section.id}.table[{table.id}]",
                suggestion=(
                    "Использовать формат «Таблица 1 — Название» (длинное тире —, не дефис)"
                ),
                details={"table_id": table.id, "caption": text},
            )
        )
    return violations


# Извлечь номер из подписи таблицы: «Таблица 1 — Название», «Таблица 12».
_TABLE_NUMBER_RE = re.compile(r"^Таблица\s+(\d+)")


def _iter_paragraphs(items: Sequence[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph (через LogicalSection.children).

    Note: Table.caption — это `list[InlineElement]`, не Paragraph, поэтому
    автоматически исключается (для B.08 это важно: ссылки в caption не
    должны считаться текстовыми ссылками на таблицу).
    """
    result: list[Paragraph] = []
    for item in items:
        if isinstance(item, Paragraph):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_paragraphs(item.children))
    return result


def _all_paragraphs(document: Document) -> list[Paragraph]:
    """Все Paragraph документа (плоско, со всех PageSection)."""
    paragraphs: list[Paragraph] = []
    for ps in document.page_sections:
        paragraphs.extend(_iter_paragraphs(ps.content))
    return paragraphs


def _paragraph_text(paragraph: Paragraph) -> str:
    """Склеить весь текст параграфа из TextRun-ов."""
    return "".join(el.text for el in paragraph.content if isinstance(el, TextRun))


@register("B.09")
def check_table_numbering_continuous(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Сквозная нумерация таблиц: номера должны идти 1, 2, 3, ...

    Извлекает номер из caption по regex `^Таблица\\s+(\\d+)`. Пустые
    подписи пропускаются (это случай B.01).

    Возможные нарушения:
    - пропуск: после таблицы N ожидается N+1, найден M
    - дубликат: один и тот же номер встречается у двух таблиц
    """
    violations: list[Violation] = []
    numbered: list[tuple[Table, int]] = []
    for _ps, table in _all_tables(document):
        text = _caption_text(table.caption)
        if not text:
            continue
        match = _TABLE_NUMBER_RE.match(text)
        if not match:
            continue
        try:
            numbered.append((table, int(match.group(1))))
        except ValueError:
            continue

    if not numbered:
        return violations

    seen: dict[int, Table] = {}
    expected = 1
    for table, num in numbered:
        if num in seen:
            previous = seen[num]
            violations.append(
                Violation(
                    check_code="B.09",
                    severity="error",
                    message=(
                        f"Номер {num} встречается у двух таблиц: «{previous.id}» и «{table.id}»"
                    ),
                    location=f"table[{table.id}]",
                    suggestion=(
                        "Перенумеровать таблицы так, чтобы каждая имела уникальный сквозной номер"
                    ),
                    details={
                        "table_id": table.id,
                        "duplicate_of": previous.id,
                        "number": str(num),
                    },
                )
            )
            continue
        seen[num] = table
        if num != expected:
            violations.append(
                Violation(
                    check_code="B.09",
                    severity="error",
                    message=(
                        f"После таблицы {expected - 1} ожидается таблица {expected}, найдено {num}"
                    ),
                    location=f"table[{table.id}]",
                    suggestion=(
                        f"Перенумеровать таблицу: «Таблица {expected}» вместо «Таблица {num}»"
                    ),
                    details={
                        "table_id": table.id,
                        "expected": str(expected),
                        "found": str(num),
                    },
                )
            )
            expected = num + 1
        else:
            expected += 1

    return violations


# Регэкспы для поиска ссылок на таблицу N в тексте параграфа (не в caption).
# Шаблоны типа «табл. 1», «таблица 1», «таблице 1», «таблицу 1».
def _table_reference_patterns(num: int) -> list[re.Pattern[str]]:
    """Сформировать regex'ы для поиска ссылок на таблицу с номером N."""
    return [
        re.compile(rf"таблиц[аеу]\s+{num}\b", re.IGNORECASE),
        re.compile(rf"табл\.\s*{num}\b", re.IGNORECASE),
    ]


@register("B.08")
def check_table_referenced_in_text(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """На каждую таблицу должна быть ссылка в тексте.

    Извлекает номер N из caption таблицы и ищет в склеенном тексте всех
    Paragraph (не Table.caption!) упоминание вида `таблица N`, `табл. N`,
    `таблице N`, `таблицу N` (case-insensitive). Если ни одной ссылки —
    Violation. Пустые подписи пропускаются (B.01).
    """
    violations: list[Violation] = []

    # Склеиваем текст только из Paragraph — подписи таблиц в Table.caption
    # сюда не попадают, поэтому ссылки в самой подписи не учитываются.
    all_text = "\n".join(_paragraph_text(p) for p in _all_paragraphs(document))

    for page_section, table in _all_tables(document):
        text = _caption_text(table.caption)
        if not text:
            continue
        match = _TABLE_NUMBER_RE.match(text)
        if not match:
            continue
        try:
            num = int(match.group(1))
        except ValueError:
            continue

        if any(p.search(all_text) for p in _table_reference_patterns(num)):
            continue

        violations.append(
            Violation(
                check_code="B.08",
                severity="error",
                message=(f"В тексте отсутствует ссылка на таблицу {num} «{table.id}»"),
                location=f"page_sections.{page_section.id}.table[{table.id}]",
                suggestion=(
                    f"Добавить в текст ссылку вида «см. таблицу {num}» или «в таблице {num}»"
                ),
                details={"table_id": table.id, "number": str(num)},
            )
        )

    return violations


def _document_blocks_linear(document: Document) -> list[Block]:
    """Все Block-и документа в порядке появления (для проверок порядка)."""
    blocks: list[Block] = []
    for ps in document.page_sections:
        blocks.extend(_iter_linear_blocks(ps.content))
    return blocks


def _iter_linear_blocks(items: Sequence[LogicalSection | Block]) -> list[Block]:
    """Линейный список Block-ов; рекурсивно обходит LogicalSection.children."""
    result: list[Block] = []
    for item in items:
        if isinstance(item, LogicalSection):
            result.extend(_iter_linear_blocks(item.children))
        elif isinstance(item, Block):
            result.append(item)
    return result


@register("B.11")
def check_table_reference_precedes(document: Document, profile: Profile) -> list[Violation]:
    """Таблица должна располагаться ПОСЛЕ первого упоминания в тексте.

    ГОСТ 7.32-2017 п. 6.5.2: таблицу помещают после абзаца с первой
    ссылкой на неё. Аналог I.07 для рисунков (severity=warning). Если
    ссылок на таблицу нет совсем — это случай B.08, здесь не дублируем.
    """
    violations: list[Violation] = []
    blocks = _document_blocks_linear(document)

    for idx, block in enumerate(blocks):
        if not isinstance(block, Table):
            continue
        text = _caption_text(block.caption)
        if not text:
            continue
        match = _TABLE_NUMBER_RE.match(text)
        if not match:
            continue
        try:
            num = int(match.group(1))
        except ValueError:
            continue

        before_text = "\n".join(
            _paragraph_text(b) for b in blocks[:idx] if isinstance(b, Paragraph)
        )
        after_text = "\n".join(
            _paragraph_text(b) for b in blocks[idx + 1 :] if isinstance(b, Paragraph)
        )
        patterns = _table_reference_patterns(num)
        if any(p.search(before_text) for p in patterns):
            continue
        if not any(p.search(after_text) for p in patterns):
            # Ссылок нет ни до, ни после — случай B.08, не дублируем.
            continue

        violations.append(
            Violation(
                check_code="B.11",
                severity="warning",
                message=(
                    f"Ссылка на таблицу {num} в тексте идёт после самой "
                    f"таблицы — она должна предшествовать таблице"
                ),
                location=f"table[{block.id}]",
                suggestion=(
                    f"Перенесите упоминание «таблица {num}» в текст ДО самой "
                    f"таблицы (например, «В таблице {num} приведены ...»)"
                ),
                details={"table_id": block.id, "number": str(num)},
            )
        )

    return violations


@register("B.06")
def check_table_cell_font_size(document: Document, profile: Profile) -> list[Violation]:
    """В ячейках таблицы шрифт должен быть `cell_font_size_pt` (по умолчанию 12pt).

    Параметры:
    - `cell_font_size_pt` (float, default 12): ожидаемый кегль в ячейках.
    - `cell_line_spacing` (float, default 1.0): не проверяется на Фазе 2
      (line_spacing не хранится на уровне ячейки в текущей модели).

    Для каждой Table проверяется любой TextRun в headers и rows с непустым
    `size_pt`: если размер отличается от ожидаемого — порождается один
    Violation на таблицу с указанием найденного размера. Если у TextRun
    `size_pt is None`, размер наследуется от стиля и не проверяется.
    """
    violations: list[Violation] = []
    config = profile.checks.get("B.06")
    expected_size = 12.0
    if config and config.params.get("cell_font_size_pt") is not None:
        try:
            expected_size = float(config.params["cell_font_size_pt"])
        except (TypeError, ValueError):
            expected_size = 12.0

    for page_section, table in _all_tables(document):
        wrong_size: float | None = None
        for cell in _iter_table_cells(table):
            for element in cell:
                if not isinstance(element, TextRun):
                    continue
                if element.size_pt is None:
                    continue
                if element.size_pt != expected_size:
                    wrong_size = element.size_pt
                    break
            if wrong_size is not None:
                break

        if wrong_size is None:
            continue

        violations.append(
            Violation(
                check_code="B.06",
                severity="warning",
                message=(
                    f"В ячейках таблицы «{table.id}» найден кегль "
                    f"{wrong_size} pt, ожидается {expected_size} pt"
                ),
                location=f"page_sections.{page_section.id}.table[{table.id}]",
                suggestion=(f"Выставить шрифту в ячейках таблицы размер {expected_size} pt"),
                details={
                    "table_id": table.id,
                    "expected_pt": str(expected_size),
                    "found_pt": str(wrong_size),
                },
            )
        )

    return violations


def _iter_table_cells(table: Table) -> list[list[InlineElement]]:
    """Все ячейки таблицы (headers + rows) как плоский список."""
    cells: list[list[InlineElement]] = []
    for header_cell in table.headers:
        cells.append(header_cell)
    for row in table.rows:
        for cell in row:
            cells.append(cell)
    return cells


def _cell_is_empty(cell: list[InlineElement]) -> bool:
    """True, если в ячейке нет ни одного TextRun с непустым текстом."""
    for element in cell:
        if isinstance(element, TextRun) and element.text and element.text.strip():
            return False
    return True


@register("B.07")
def check_table_empty_cells_dash(document: Document, profile: Profile) -> list[Violation]:
    """Пустые ячейки таблицы должны быть заполнены прочерком.

    Параметры:
    - `allow_first_column_empty` (bool, default False): если True, пустые
      ячейки в первой колонке (col 0) допускаются (нумерация строк и т.п.).

    Обходим headers и rows. Если найдена ячейка с полностью пустым текстом
    (все TextRun-ы после strip пусты) — один Violation на таблицу с
    указанием первой найденной координаты («row 2, col 3»).
    """
    violations: list[Violation] = []
    config = profile.checks.get("B.07")
    allow_first_col = False
    if config and config.params.get("allow_first_column_empty") is not None:
        allow_first_col = bool(config.params["allow_first_column_empty"])

    for page_section, table in _all_tables(document):
        # row=0 — это «строка заголовков» (headers); далее rows нумеруются от 1.
        empty_coord: tuple[int, int] | None = None
        for col_idx, header_cell in enumerate(table.headers):
            if allow_first_col and col_idx == 0:
                continue
            if _cell_is_empty(header_cell):
                empty_coord = (0, col_idx)
                break
        if empty_coord is None:
            for row_idx, row in enumerate(table.rows, start=1):
                for col_idx, cell in enumerate(row):
                    if allow_first_col and col_idx == 0:
                        continue
                    if _cell_is_empty(cell):
                        empty_coord = (row_idx, col_idx)
                        break
                if empty_coord is not None:
                    break

        if empty_coord is None:
            continue

        row_idx, col_idx = empty_coord
        violations.append(
            Violation(
                check_code="B.07",
                severity="info",
                message=(
                    f"В таблице «{table.id}» пустая ячейка "
                    f"(row {row_idx}, col {col_idx}) — рекомендуется поставить прочерк"
                ),
                location=f"page_sections.{page_section.id}.table[{table.id}]",
                suggestion="Заполнить пустую ячейку прочерком «—»",
                details={
                    "table_id": table.id,
                    "row": str(row_idx),
                    "col": str(col_idx),
                },
            )
        )

    return violations


@register("B.10")
def check_table_not_empty(document: Document, profile: Profile) -> list[Violation]:
    """B.10 — таблица не должна быть пустой.

    Таблица считается пустой, если:
    * нет ни одной data-строки (только headers), ИЛИ
    * есть строки, но во всех ячейках текст пустой/whitespace.

    Пустая таблица обычно — забытый placeholder при копировании структуры
    или ошибка при редактировании.
    """
    _ = profile
    violations: list[Violation] = []
    for _ps, table in _all_tables(document):
        if _is_table_empty(table):
            violations.append(
                Violation(
                    check_code="B.10",
                    severity="warning",
                    message=(
                        f"Таблица «{_table_caption_text(table)}» пуста — нет данных в строках"
                    ),
                    location=f"tables[{table.id}]",
                    suggestion=(
                        "Заполнить таблицу данными или удалить её, "
                        "если она оказалась пустой по ошибке"
                    ),
                    details={"table_id": table.id},
                )
            )
    return violations


def _is_table_empty(table: Table) -> bool:
    """True если таблица не имеет содержательных data-строк."""
    if not table.rows:
        return True
    for row in table.rows:
        for cell in row:
            for el in cell:
                if hasattr(el, "text") and (el.text or "").strip():
                    return False
    return True


def _table_caption_text(table: Table) -> str:
    """Краткое описание таблицы — её caption или id."""
    parts: list[str] = []
    for el in table.caption:
        if hasattr(el, "text") and isinstance(el.text, str):
            parts.append(el.text)
    txt = "".join(parts).strip()
    return txt if txt else table.id


__all__ = [
    "check_table_caption_above",
    "check_table_caption_format",
    "check_table_cell_font_size",
    "check_table_continuation_header",
    "check_table_empty_cells_dash",
    "check_table_has_caption",
    "check_table_header_repeats",
    "check_table_not_empty",
    "check_table_numbering_continuous",
    "check_table_referenced_in_text",
]
