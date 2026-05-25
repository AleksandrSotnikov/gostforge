"""A.* — проверки сокращений и аббревиатур."""

# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

import re
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

# Аббревиатура — 2..10 заглавных букв (кириллических или латинских).
# Не допускаем цифры в составе — тогда это код/идентификатор, не аббр.
_ABBR_RE = re.compile(r"\b([A-ZА-ЯЁ]{2,10})\b")


# Общеизвестные аббревиатуры, не требующие расшифровки. Можно расширять
# через `checks.A.01.params.known_abbreviations` в профиле.
_DEFAULT_KNOWN_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "ГОСТ",
        "ВКР",
        "НИР",
        "ЕСКД",
        "FAQ",
        "URL",
        "DOI",
        "PDF",
        "XML",
    }
)

# Предел длины превью текста в сообщении.
_PREVIEW_LIMIT = 80


def _iter_paragraphs(items: Sequence[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph (через LogicalSection.children)."""
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


def _preview(text: str) -> str:
    """Усечь текст до короткого превью для сообщения."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= _PREVIEW_LIMIT:
        return cleaned
    return cleaned[: _PREVIEW_LIMIT - 1] + "…"


def _has_expansion(text: str, abbr: str, abbr_start: int, abbr_end: int) -> bool:
    """Проверить, есть ли при первом употреблении паттерн расшифровки.

    Принимаются два варианта:
    - «<фраза> (АББР)» — аббревиатура в скобках, перед ней — слово.
      Эвристически: текст ДО `abbr_start` оканчивается на `(`, а перед
      этой скобкой — хотя бы одно слово (буквенный фрагмент).
    - «АББР (<расшифровка>)» — сразу после `АББР` идёт `(...)` с
      непустым текстом.
    """
    _ = abbr  # параметр оставлен для будущих расширений.
    # Вариант «АББР (расшифровка)»: сразу после abbr — «(...)».
    # Допускаем пробел(ы) перед «(».
    after_match = re.match(r"\s*\(([^)]+)\)", text[abbr_end:])
    if after_match and after_match.group(1).strip():
        return True

    # Вариант «<фраза> (АББР)»: текст ДО abbr оканчивается на «(» (с
    # учётом пробелов), а непосредственно перед «(» есть слово.
    before = text[:abbr_start].rstrip()
    if before.endswith("("):
        before_paren = before[:-1].rstrip()
        # Проверяем, что перед скобкой есть слово (буквенный фрагмент).
        if re.search(r"[A-Za-zА-Яа-яЁё]\s*$", before_paren):
            return True

    return False


@register("A.01")
def check_abbreviation_first_use_explained(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Аббревиатура должна быть расшифрована при первом употреблении.

    Эвристика:
    1. Найти все аббревиатуры (2..10 заглавных букв, кириллических или
       латинских) во всех Paragraph.
    2. Для каждой уникальной аббревиатуры найти ПЕРВОЕ употребление в
       документе.
    3. Если в её первом употреблении нет паттерна расшифровки —
       Violation (severity=warning, так как это эвристика).

    Параметры профиля (`checks.A.01.params`):
    - `known_abbreviations`: список аббревиатур, которые считаются
      общеизвестными и НЕ требуют расшифровки. Добавляется ко
      встроенному дефолтному списку (`ГОСТ`, `ВКР`, `НИР`, `ЕСКД`,
      `FAQ`, `URL`, `DOI`, `PDF`, `XML`).
    """
    violations: list[Violation] = []
    config = profile.checks.get("A.01")
    known: set[str] = set(_DEFAULT_KNOWN_ABBREVIATIONS)
    if config and config.params.get("known_abbreviations"):
        for item in config.params["known_abbreviations"]:
            if isinstance(item, str):
                known.add(item)

    paragraphs = _all_paragraphs(document)

    # Найдём первое употребление каждой уникальной аббревиатуры.
    first_use: dict[str, tuple[Paragraph, str, int, int]] = {}
    for paragraph in paragraphs:
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _ABBR_RE.finditer(text):
            abbr = match.group(1)
            if abbr in first_use:
                continue
            first_use[abbr] = (paragraph, text, match.start(1), match.end(1))

    for abbr, (paragraph, text, start, end) in first_use.items():
        if abbr in known:
            continue
        if _has_expansion(text, abbr, start, end):
            continue
        violations.append(
            Violation(
                check_code="A.01",
                severity="warning",
                message=(
                    f"Аббревиатура «{abbr}» при первом употреблении в абзаце "
                    f"«{_preview(text)}» не сопровождается расшифровкой"
                ),
                location=f"paragraph[{paragraph.id}]",
                suggestion=(
                    f"При первом упоминании указать расшифровку в формате "
                    f"«Полное название ({abbr})» или «{abbr} "
                    f"(полное название)»"
                ),
                details={"paragraph_id": paragraph.id, "abbreviation": abbr},
            )
        )

    return violations


# --- Хелперы для A.02, A.03 -----------------------------------------------


def _heading_text(elements: Sequence[InlineElement]) -> str:
    """Склеить inline-содержимое заголовка в строку."""
    return "".join(el.text for el in elements if isinstance(el, TextRun))


def _iter_logical_sections(
    items: Sequence[object],
) -> list[LogicalSection]:
    """Рекурсивно собрать все LogicalSection (всех уровней)."""
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


def _collect_abbreviations(paragraphs: Sequence[Paragraph]) -> set[str]:
    """Собрать множество уникальных аббревиатур из текста абзацев.

    Используется в A.01/A.02. Возвращает аббревиатуры в исходном
    написании (как нашли в тексте), 2..10 заглавных букв.
    """
    found: set[str] = set()
    for paragraph in paragraphs:
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _ABBR_RE.finditer(text):
            found.add(match.group(1))
    return found


# --- A.02 ------------------------------------------------------------------


# Заголовки-алиасы для списка сокращений (нормализуем к lowercase).
_ABBR_LIST_HEADINGS: frozenset[str] = frozenset(
    {
        "список сокращений",
        "перечень сокращений",
        "сокращения и условные обозначения",
        "перечень сокращений и условных обозначений",
        "список сокращений и условных обозначений",
    }
)


def _normalize_heading(text: str) -> str:
    """Нормализация заголовка для сравнения (lowercase + collapse whitespace)."""
    return " ".join(text.lower().split())


def _has_abbreviations_section(document: Document) -> bool:
    """Проверить, есть ли в документе LogicalSection-список сокращений."""
    for section in _all_logical_sections(document):
        heading = _normalize_heading(_heading_text(section.heading))
        if heading in _ABBR_LIST_HEADINGS:
            return True
    return False


@register("A.02")
def check_abbreviations_list_required(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Если в тексте >N аббревиатур, в документе должен быть «Список сокращений».

    Параметры профиля (`checks.A.02.params`):
    - `threshold`: пороговое число уникальных аббревиатур (по умолчанию 5).

    Логика обнаружения аббревиатур такая же, как в A.01: 2..10 заглавных
    букв (кириллических или латинских). Известные аббревиатуры из A.01
    (ГОСТ, URL и т.п.) в подсчёт ВКЛЮЧАЮТСЯ — пользователь, использующий
    много аббревиатур (включая известные), всё равно должен иметь
    список сокращений для удобства читателя.
    """
    violations: list[Violation] = []
    config = profile.checks.get("A.02")
    threshold = 5
    if config and config.params.get("threshold") is not None:
        try:
            threshold = int(config.params["threshold"])
        except (TypeError, ValueError):
            threshold = 5

    paragraphs = _all_paragraphs(document)
    abbreviations = _collect_abbreviations(paragraphs)
    if len(abbreviations) <= threshold:
        return violations

    if _has_abbreviations_section(document):
        return violations

    violations.append(
        Violation(
            check_code="A.02",
            severity="warning",
            message=(
                f"В тексте обнаружено {len(abbreviations)} различных "
                f"аббревиатур (порог {threshold}), однако раздел "
                f"«Список сокращений» в документе отсутствует"
            ),
            location="document",
            suggestion=(
                "Добавить раздел уровня 1 с заголовком «Список "
                "сокращений» (или «Перечень сокращений», «Сокращения "
                "и условные обозначения») с расшифровкой использованных "
                "аббревиатур"
            ),
            details={
                "abbreviation_count": str(len(abbreviations)),
                "threshold": str(threshold),
            },
        )
    )

    return violations


__all__ = [
    "check_abbreviation_first_use_explained",
    "check_abbreviations_list_required",
]
