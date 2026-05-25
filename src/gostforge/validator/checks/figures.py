"""I.* — проверки рисунков."""

# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

import re
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

# Формат подписи рисунка по ГОСТ 7.32-2017: «Рисунок N — Название».
# Между номером и тире — один пробел; тире длинное (—), допускаем также
# среднее (–) и обычный дефис (-) как «не строго» — но в правильном
# случае всё равно сообщаем suggestion с длинным тире.
_FIGURE_CAPTION_RE = re.compile(
    r"^Рис(?:унок)?\s+\d+(?:\.\d+)?\s+[—–-]\s+\S"
)

# Альтернативный вариант, когда параметр allow_dot_after_number=True:
# «Рисунок 1. Название» — без длинного тире, с точкой после номера.
_FIGURE_CAPTION_DOT_RE = re.compile(
    r"^Рис(?:унок)?\s+\d+(?:\.\d+)?\.\s+\S"
)


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


def _caption_text(elements: Sequence[InlineElement]) -> str:
    """Склеить подпись в строку — только TextRun-ы (CrossRef игнорируются)."""
    return "".join(el.text for el in elements if isinstance(el, TextRun)).strip()


@register("I.03")
def check_figure_caption_format(
    document: Document, profile: Profile
) -> list[Violation]:
    """Подпись рисунка должна быть в формате «Рисунок N — Название».

    Параметры:
    - `allow_dot_after_number` (bool, default False): если True, также
      принимается «Рисунок 1. Название» (с точкой после номера).

    Пустые подписи не проверяются — это случай I.01.
    """
    violations: list[Violation] = []
    config = profile.checks.get("I.03")
    allow_dot = False
    if config and config.params.get("allow_dot_after_number") is not None:
        allow_dot = bool(config.params["allow_dot_after_number"])

    for page_section, figure in _all_figures(document):
        text = _caption_text(figure.caption)
        if not text:
            # Пустая подпись — это I.01, не дублируем.
            continue
        if _FIGURE_CAPTION_RE.match(text):
            continue
        if allow_dot and _FIGURE_CAPTION_DOT_RE.match(text):
            continue
        violations.append(
            Violation(
                check_code="I.03",
                severity="error",
                message=(
                    f"Подпись рисунка «{text}» не соответствует формату "
                    f"«Рисунок N — Название»"
                ),
                location=f"page_sections.{page_section.id}.figure[{figure.id}]",
                suggestion=(
                    "Использовать формат «Рисунок 1 — Название» "
                    "(длинное тире —, не дефис)"
                ),
                details={"figure_id": figure.id, "caption": text},
            )
        )
    return violations


# Извлечь номер из подписи рисунка: «Рисунок 1 — Название», «Рис. 2», «Рис 3».
_FIGURE_NUMBER_RE = re.compile(r"^Рис(?:унок)?\.?\s+(\d+)")


@register("I.05")
def check_figure_numbering_continuous(
    document: Document, profile: Profile  # noqa: ARG001
) -> list[Violation]:
    """Сквозная нумерация рисунков: номера должны идти 1, 2, 3, ...

    Извлекает номер из caption по regex `^Рис(?:унок)?\\.?\\s+(\\d+)`.
    Пустые подписи пропускаются (это случай I.01).

    Возможные нарушения:
    - пропуск: после рисунка N ожидается N+1, найден M (M > N+1)
    - дубликат: один и тот же номер встречается у двух рисунков
    """
    violations: list[Violation] = []
    numbered: list[tuple[Figure, int]] = []
    for _ps, figure in _all_figures(document):
        text = _caption_text(figure.caption)
        if not text:
            continue
        match = _FIGURE_NUMBER_RE.match(text)
        if not match:
            continue
        try:
            numbered.append((figure, int(match.group(1))))
        except ValueError:
            continue

    if not numbered:
        return violations

    seen: dict[int, Figure] = {}
    expected = 1
    for figure, num in numbered:
        if num in seen:
            previous = seen[num]
            violations.append(
                Violation(
                    check_code="I.05",
                    severity="error",
                    message=(
                        f"Номер {num} встречается у двух рисунков: "
                        f"«{previous.id}» и «{figure.id}»"
                    ),
                    location=f"figure[{figure.id}]",
                    suggestion=(
                        f"Перенумеровать рисунки так, чтобы каждый имел "
                        f"уникальный сквозной номер"
                    ),
                    details={
                        "figure_id": figure.id,
                        "duplicate_of": previous.id,
                        "number": str(num),
                    },
                )
            )
            continue
        seen[num] = figure
        if num != expected:
            violations.append(
                Violation(
                    check_code="I.05",
                    severity="error",
                    message=(
                        f"После рисунка {expected - 1} ожидается рисунок "
                        f"{expected}, найдено {num}"
                    ),
                    location=f"figure[{figure.id}]",
                    suggestion=(
                        f"Перенумеровать рисунок: «Рисунок {expected}» вместо "
                        f"«Рисунок {num}»"
                    ),
                    details={
                        "figure_id": figure.id,
                        "expected": str(expected),
                        "found": str(num),
                    },
                )
            )
            expected = num + 1
        else:
            expected += 1

    return violations


__all__ = [
    "check_figure_caption_format",
    "check_figure_has_caption",
    "check_figure_numbering_continuous",
]
