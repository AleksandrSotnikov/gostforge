# ruff: noqa: RUF002, RUF003

"""H.* — фиксеры заголовков логических разделов."""

from __future__ import annotations

import re

from gostforge.model import (
    Block,
    Document,
    LogicalSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import FixApplied, register

# Шаблон «номер заголовка с точкой»: «1. Введение», «1.2. Анализ».
# Группы: 1 — номер, 2 — точка, 3 — следующий пробельный символ.
_NUMBER_WITH_DOT = re.compile(r"^(\d+(?:\.\d+)*)(\.)(\s)")


def _iter_logical_sections(
    items: list[LogicalSection | Block],
) -> list[LogicalSection]:
    """Рекурсивно собрать все LogicalSection документа."""
    result: list[LogicalSection] = []
    for item in items:
        if isinstance(item, LogicalSection):
            result.append(item)
            result.extend(_iter_logical_sections(item.children))
    return result


def _all_logical_sections(document: Document) -> list[LogicalSection]:
    """Все LogicalSection документа (плоско, со всех PageSection)."""
    sections: list[LogicalSection] = []
    for ps in document.page_sections:
        sections.extend(_iter_logical_sections(ps.content))
    return sections


def _heading_runs(section: LogicalSection) -> list[TextRun]:
    """TextRun-ы из heading логического раздела."""
    return [el for el in section.heading if isinstance(el, TextRun)]


def _heading_location(section: LogicalSection) -> str:
    """Стандартный путь в модели для FixApplied.location."""
    return f"page_sections.*.logical_section[{section.id}].heading"


@register("H.03")
def fix_dot_after_heading_number(
    document: Document, profile: Profile
) -> list[FixApplied]:
    """Убрать точку после номера в заголовке.

    Заменяет «1. Введение» → «1 Введение», «1.2. Анализ» → «1.2 Анализ».
    Точка убирается только сразу после номера, точки в любом другом месте
    заголовка сохраняются. Номер всегда находится в начале первого
    TextRun-а — там и применяется замена.
    """
    applied: list[FixApplied] = []
    for section in _all_logical_sections(document):
        runs = _heading_runs(section)
        if not runs:
            continue
        first = runs[0]
        if not first.text:
            continue
        match = _NUMBER_WITH_DOT.match(first.text)
        if not match:
            continue
        number = match.group(1)
        whitespace = match.group(3)
        new_prefix = f"{number}{whitespace}"
        new_text = new_prefix + first.text[match.end() :]
        first.text = new_text
        applied.append(
            FixApplied(
                fixer_code="H.03",
                location=_heading_location(section),
                description="Убрана точка после номера заголовка",
                details={"number": number},
            )
        )
    return applied


@register("H.08")
def fix_heading_trailing_dot(
    document: Document, profile: Profile
) -> list[FixApplied]:
    """Убрать точку (или многоточие) в конце заголовка.

    Не трогает `?` и `:` — они по ГОСТ допустимы. Работает с последним
    непустым TextRun-ом заголовка: отрезает завершающие `...`, `…` или
    одиночную `.`. Хвостовые пробелы предварительно учитываются.
    """
    applied: list[FixApplied] = []
    for section in _all_logical_sections(document):
        runs = _heading_runs(section)
        last_run: TextRun | None = None
        for run in runs:
            if run.text:
                last_run = run
        if last_run is None:
            continue

        original = last_run.text
        # Учитываем хвостовые пробелы при определении окончания, но при
        # записи сохраняем их (rstrip-ом займётся T.09, не наш фиксер).
        stripped = original.rstrip()
        if not stripped:
            continue
        trailing_ws = original[len(stripped) :]

        if stripped.endswith("..."):
            new_stripped = stripped[:-3]
            suffix = "..."
        elif stripped.endswith("…"):
            new_stripped = stripped[:-1]
            suffix = "…"
        elif stripped.endswith("."):
            new_stripped = stripped[:-1]
            suffix = "."
        else:
            continue

        last_run.text = new_stripped + trailing_ws
        applied.append(
            FixApplied(
                fixer_code="H.08",
                location=_heading_location(section),
                description="Убрана точка в конце заголовка",
                details={"removed": suffix},
            )
        )
    return applied


__all__ = [
    "fix_dot_after_heading_number",
    "fix_heading_trailing_dot",
]
