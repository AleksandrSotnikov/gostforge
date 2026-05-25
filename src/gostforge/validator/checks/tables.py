"""B.* — проверки таблиц."""

# ruff: noqa: RUF001, RUF002

from __future__ import annotations

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


__all__ = ["check_table_has_caption"]
