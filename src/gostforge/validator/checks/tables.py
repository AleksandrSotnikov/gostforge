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


__all__ = ["check_table_caption_format", "check_table_has_caption"]
