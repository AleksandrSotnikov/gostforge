"""S.* — проверки структуры работы (наличие обязательных разделов, их порядок)."""

from __future__ import annotations

from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    InlineElement,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register
from .headings import iter_logical_sections


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


def _first_paragraph(section: LogicalSection) -> Paragraph | None:
    """Найти первый Paragraph среди прямых детей раздела."""
    for child in section.children:
        if isinstance(child, Paragraph):
            return child
    return None


@register("S.06")
def check_section_page_break(document: Document, profile: Profile) -> list[Violation]:
    """Раздел указанного уровня должен начинаться с новой страницы.

    Параметр профиля `checks.S.06.params.required_for_level` (по умолчанию 1)
    задаёт, для каких уровней разделов требуется разрыв страницы.

    Семантика Фазы 1 — «мягкая»: нарушением считается только случай,
    когда у первого Paragraph раздела `page_break_before` явно равен
    False. Если значение None (унаследовано/не задано парсером явно) —
    не считаем нарушением, чтобы не плодить ложные срабатывания
    (разрыв может быть задан через Word-стиль заголовка).

    Самый первый LogicalSection документа пропускается — он по умолчанию
    начинается с первой страницы.
    """
    violations: list[Violation] = []
    config = profile.checks.get("S.06")
    required_level = 1
    if config and config.params.get("required_for_level") is not None:
        try:
            required_level = int(config.params["required_for_level"])
        except (TypeError, ValueError):
            required_level = 1

    sections: list[LogicalSection] = []
    for ps in document.page_sections:
        sections.extend(iter_logical_sections(ps.content))

    level_sections = [s for s in sections if s.level == required_level]
    # Первый раздел нужного уровня — на первой странице, разрыв не нужен.
    for section in level_sections[1:]:
        first_para = _first_paragraph(section)
        if first_para is None:
            continue
        if first_para.page_break_before is False:
            heading = _heading_text(section.heading)
            violations.append(
                Violation(
                    check_code="S.06",
                    severity="error",
                    message=(
                        f"Раздел «{heading}» (уровень {required_level}) не начинается "
                        f"с новой страницы"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        "Включить разрыв страницы перед заголовком "
                        "(Word: «Разрыв страницы перед» в свойствах абзаца)"
                    ),
                    details={"section_id": section.id, "level": str(required_level)},
                )
            )

    return violations


__all__ = [
    "check_required_sections",
    "check_section_page_break",
]
