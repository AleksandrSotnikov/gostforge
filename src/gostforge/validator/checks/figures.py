"""I.* — проверки рисунков."""

# ruff: noqa: RUF001, RUF002

from __future__ import annotations

from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    Figure,
    InlineElement,
    LogicalSection,
    PageSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register


def _iter_figures(items: Sequence[LogicalSection | Block]) -> list[Figure]:
    """Рекурсивно собрать все Figure из content (через LogicalSection.children)."""
    result: list[Figure] = []
    for item in items:
        if isinstance(item, Figure):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_figures(item.children))
    return result


def _all_figures(document: Document) -> list[tuple[PageSection, Figure]]:
    """Все Figure документа — со ссылкой на PageSection (для location)."""
    result: list[tuple[PageSection, Figure]] = []
    for ps in document.page_sections:
        for figure in _iter_figures(ps.content):
            result.append((ps, figure))
    return result


def _has_text(elements: Sequence[InlineElement]) -> bool:
    """True, если в списке есть хотя бы один TextRun с непустым текстом."""
    return any(
        isinstance(el, TextRun) and el.text and el.text.strip() for el in elements
    )


@register("I.01")
def check_figure_has_caption(
    document: Document, profile: Profile  # noqa: ARG001
) -> list[Violation]:
    """Каждый рисунок должен иметь подпись «Рисунок N — Название»."""
    violations: list[Violation] = []
    for page_section, figure in _all_figures(document):
        if _has_text(figure.caption):
            continue
        violations.append(
            Violation(
                check_code="I.01",
                severity="error",
                message=f"У рисунка «{figure.id}» отсутствует подпись",
                location=f"page_sections.{page_section.id}.figure[{figure.id}]",
                suggestion="Добавить под рисунком подпись в формате «Рисунок N — Название»",
                details={"figure_id": figure.id},
            )
        )
    return violations


__all__ = ["check_figure_has_caption"]
