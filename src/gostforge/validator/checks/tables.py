"""B.* — проверки таблиц."""

# ruff: noqa: RUF001, RUF002

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
_TABLE_CAPTION_RE = re.compile(
    r"^Таблица\s+\d+(?:\.\d+)?\s+[—–-]\s+\S"
)

# Альтернативный вариант: «Таблица 1. Название».
_TABLE_CAPTION_DOT_RE = re.compile(
    r"^Таблица\s+\d+(?:\.\d+)?\.\s+\S"
)


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
    return any(
        isinstance(el, TextRun) and el.text and el.text.strip() for el in elements
    )


@register("B.02")
def check_table_caption_above(
    document: Document,  # noqa: ARG001
    profile: Profile,  # noqa: ARG001
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
    document: Document,  # noqa: ARG001
    profile: Profile,  # noqa: ARG001
) -> list[Violation]:
    """При переносе таблицы на новую страницу должен быть заголовок «Продолжение таблицы N» (заглушка Фазы 2).

    На Фазе 2 — заглушка: парсер не сохраняет разбивку на страницы, без
    рендеринга это нельзя проверить. Когда появится модель страниц
    (PageBreak/PageLayout), здесь будет проверка наличия заголовка
    «Продолжение таблицы N» на каждой странице, куда переносится таблица.
    """
    return []


@register("B.01")
def check_table_has_caption(
    document: Document, profile: Profile  # noqa: ARG001
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
def check_table_caption_format(
    document: Document, profile: Profile
) -> list[Violation]:
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
                    f"Подпись таблицы «{text}» не соответствует формату "
                    f"«Таблица N — Название»"
                ),
                location=f"page_sections.{page_section.id}.table[{table.id}]",
                suggestion=(
                    "Использовать формат «Таблица 1 — Название» "
                    "(длинное тире —, не дефис)"
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
    document: Document, profile: Profile  # noqa: ARG001
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
                        f"Номер {num} встречается у двух таблиц: "
                        f"«{previous.id}» и «{table.id}»"
                    ),
                    location=f"table[{table.id}]",
                    suggestion=(
                        "Перенумеровать таблицы так, чтобы каждая имела "
                        "уникальный сквозной номер"
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
                        f"После таблицы {expected - 1} ожидается таблица "
                        f"{expected}, найдено {num}"
                    ),
                    location=f"table[{table.id}]",
                    suggestion=(
                        f"Перенумеровать таблицу: «Таблица {expected}» вместо "
                        f"«Таблица {num}»"
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
    document: Document, profile: Profile  # noqa: ARG001
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
                message=(
                    f"В тексте отсутствует ссылка на таблицу {num} «{table.id}»"
                ),
                location=f"page_sections.{page_section.id}.table[{table.id}]",
                suggestion=(
                    f"Добавить в текст ссылку вида «см. таблицу {num}» или "
                    f"«в таблице {num}»"
                ),
                details={"table_id": table.id, "number": str(num)},
            )
        )

    return violations


__all__ = [
    "check_table_caption_above",
    "check_table_caption_format",
    "check_table_continuation_header",
    "check_table_has_caption",
    "check_table_numbering_continuous",
    "check_table_referenced_in_text",
]
