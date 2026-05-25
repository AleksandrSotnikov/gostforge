"""H.* — проверки заголовков логических разделов."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from gostforge.model import (
    Block,
    Document,
    InlineElement,
    LogicalSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register


_SIZE_TOLERANCE_PT = 0.1

# Шаблон: «номер раздела с точкой/точками» в начале заголовка.
# Допустимый по ГОСТ: «1 Введение», «1.2 Анализ» — без точки в конце номера.
# НЕдопустимый: «1. Введение», «1.2. Анализ».
# Группа 1 — сам номер (1, 1.2, 1.2.3), группа 2 — точка после.
_NUMBER_WITH_DOT = re.compile(r"^(\d+(?:\.\d+)*)(\.)\s")


def _heading_text(content: Sequence[InlineElement]) -> str:
    return "".join(el.text for el in content if isinstance(el, TextRun))


def _heading_runs(content: Sequence[InlineElement]) -> list[TextRun]:
    return [el for el in content if isinstance(el, TextRun)]


def iter_logical_sections(
    items: Sequence[LogicalSection | Block],
) -> list[LogicalSection]:
    """Рекурсивно собрать все LogicalSection (всех уровней).

    Публичный хелпер — используется не только H.*, но и S.* проверками.
    """
    result: list[LogicalSection] = []
    for item in items:
        if isinstance(item, LogicalSection):
            result.append(item)
            result.extend(iter_logical_sections(item.children))
    return result


def all_logical_sections(document: Document) -> list[LogicalSection]:
    """Все LogicalSection документа (плоско, со всех PageSection)."""
    sections: list[LogicalSection] = []
    for ps in document.page_sections:
        sections.extend(iter_logical_sections(ps.content))
    return sections


# Алиасы для обратной совместимости внутри модуля.
_iter_logical_sections = iter_logical_sections
_all_logical_sections = all_logical_sections


@register("H.01")
def check_heading_1_format(document: Document, profile: Profile) -> list[Violation]:
    """Проверка формата заголовков 1 уровня.

    Сверяется с `profile.styles.extra.heading_1` (font, size_pt, bold,
    uppercase, alignment). Если у заголовка свойство явно задано и не
    совпадает с эталоном — нарушение. None значит «наследуется» —
    пропускаем.
    """
    violations: list[Violation] = []
    heading_1: dict[str, Any] = profile.styles.extra.get("heading_1", {}) or {}

    expected_font: str | None = heading_1.get("font")
    expected_size: float | None = heading_1.get("size_pt")
    expected_bold: bool | None = heading_1.get("bold")
    expected_uppercase: bool | None = heading_1.get("uppercase")
    expected_alignment: str | None = heading_1.get("alignment")

    for section in _all_logical_sections(document):
        if section.level != 1:
            continue

        text = _heading_text(section.heading)
        runs = _heading_runs(section.heading)

        if expected_uppercase is True and text and text != text.upper():
            violations.append(
                _violation(
                    "H.01",
                    f"Заголовок 1 уровня «{text}» должен быть в верхнем регистре",
                    section.id,
                    suggestion="Привести заголовок к верхнему регистру",
                )
            )

        if expected_alignment is not None:
            # Выравнивание хранится на уровне Paragraph, но heading в нашей
            # модели — list[InlineElement]. На Фазе 1 проверяем только runs.
            # Полная проверка alignment заголовков — Фаза 2 (когда заголовок
            # станет полноценным Paragraph внутри LogicalSection).
            pass

        for run in runs:
            if not run.text or not run.text.strip():
                continue
            if expected_font and run.font and run.font != expected_font:
                violations.append(
                    _violation(
                        "H.01",
                        f"В заголовке 1 уровня «{text}» использован шрифт "
                        f"«{run.font}» вместо «{expected_font}»",
                        section.id,
                        suggestion=f"Использовать шрифт «{expected_font}» в заголовках 1 уровня",
                    )
                )
            if (
                expected_size is not None
                and run.size_pt is not None
                and abs(run.size_pt - float(expected_size)) > _SIZE_TOLERANCE_PT
            ):
                violations.append(
                    _violation(
                        "H.01",
                        f"В заголовке 1 уровня «{text}» использован кегль "
                        f"{run.size_pt} pt вместо {expected_size} pt",
                        section.id,
                        suggestion=f"Использовать кегль {expected_size} pt в заголовках 1 уровня",
                    )
                )
            if expected_bold is True and run.bold is False:
                violations.append(
                    _violation(
                        "H.01",
                        f"Заголовок 1 уровня «{text}» не выделен полужирным",
                        section.id,
                        suggestion="Сделать заголовок полужирным",
                    )
                )

    return violations


@register("H.03")
def check_heading_number_no_trailing_dot(
    document: Document, profile: Profile  # noqa: ARG001
) -> list[Violation]:
    """После номера раздела в заголовке точки быть не должно.

    Допустимо: «1 Введение», «1.2 Анализ».
    НЕдопустимо: «1. Введение», «1.2. Анализ».
    """
    violations: list[Violation] = []
    for section in _all_logical_sections(document):
        text = _heading_text(section.heading)
        if not text:
            continue
        match = _NUMBER_WITH_DOT.match(text)
        if match:
            number = match.group(1)
            violations.append(
                _violation(
                    "H.03",
                    f"В заголовке «{text}» после номера «{number}» стоит точка",
                    section.id,
                    suggestion=f"Убрать точку после номера: «{number} <название>»",
                    details={"number": number},
                )
            )
    return violations


def _violation(
    code: str,
    message: str,
    section_id: str,
    *,
    suggestion: str = "",
    details: dict[str, str] | None = None,
) -> Violation:
    return Violation(
        check_code=code,
        severity="error",
        message=message,
        location=f"page_sections.*.logical_section[{section_id}]",
        suggestion=suggestion,
        details=details or {},
    )


__all__ = [
    "all_logical_sections",
    "check_heading_1_format",
    "check_heading_number_no_trailing_dot",
    "iter_logical_sections",
]
