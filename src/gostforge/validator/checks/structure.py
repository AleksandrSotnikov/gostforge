"""S.* — проверки структуры работы (наличие обязательных разделов, их порядок)."""

from __future__ import annotations

from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    InlineElement,
    LogicalSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register


# Дефолтный список обязательных разделов для ГОСТ 7.32-2017. Может быть
# переопределён через `checks.S.01.params.required_headings`.
_DEFAULT_REQUIRED_HEADINGS: list[str] = [
    "Введение",
    "Заключение",
    "Список использованных источников",
]

# Альтернативные написания для разделов: одно из них достаточно
# (например, «Список литературы» или «Список использованных источников»).
_HEADING_ALIASES: dict[str, list[str]] = {
    "Список использованных источников": ["Список литературы"],
}


def _heading_text(content: Sequence[InlineElement]) -> str:
    """Склеить inline-содержимое заголовка в чистую строку."""
    return "".join(el.text for el in content if isinstance(el, TextRun)).strip()


def _all_level1_headings(items: Sequence[LogicalSection | Block]) -> list[str]:
    """Собрать тексты всех LogicalSection первого уровня (рекурсивно)."""
    result: list[str] = []
    for item in items:
        if isinstance(item, LogicalSection):
            if item.level == 1:
                result.append(_heading_text(item.heading))
            result.extend(_all_level1_headings(item.children))
    return result


def _normalize(s: str) -> str:
    """Нормализация для сравнения: lowercase + collapse whitespace."""
    return " ".join(s.lower().split())


@register("S.01")
def check_required_sections(document: Document, profile: Profile) -> list[Violation]:
    """Проверка наличия обязательных разделов работы.

    Параметры профиля (`checks.S.01.params`):
    - `required_headings`: список ожидаемых заголовков (по умолчанию
      «Введение», «Заключение», «Список использованных источников»).
    """
    violations: list[Violation] = []
    config = profile.checks.get("S.01")
    required: list[str] = list(_DEFAULT_REQUIRED_HEADINGS)
    if config and config.params.get("required_headings"):
        required = list(config.params["required_headings"])

    found_headings: list[str] = []
    for section in document.page_sections:
        found_headings.extend(_all_level1_headings(section.content))

    normalized_found = {_normalize(h) for h in found_headings if h}

    for expected in required:
        candidates = [expected] + _HEADING_ALIASES.get(expected, [])
        if not any(_normalize(c) in normalized_found for c in candidates):
            aliases = _HEADING_ALIASES.get(expected, [])
            aliases_hint = f" (или: {', '.join(aliases)})" if aliases else ""
            violations.append(
                Violation(
                    check_code="S.01",
                    severity="error",
                    message=f"В документе отсутствует обязательный раздел «{expected}»",
                    location="page_sections.*.logical_section[level=1]",
                    suggestion=f"Добавить раздел уровня 1 с заголовком «{expected}»{aliases_hint}",
                    details={"expected": expected, "found_headings": "; ".join(found_headings)},
                )
            )
    return violations


__all__ = ["check_required_sections"]
