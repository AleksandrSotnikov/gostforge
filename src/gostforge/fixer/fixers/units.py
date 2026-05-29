"""U.* — фиксеры единиц измерения (ГОСТ Р 8.000-2015 СИ).

Симметрично проверкам категории U.*:
* U.01 — обычный пробел между числом и единицей → неразрывный (U+00A0).
* U.02 — точка/запятая между числом и единицей → пробел (NBSP) + единица.
* U.03 — лишняя точка после единицы → убрать (с теми же исключениями,
  что и в проверке: «1990 г.» — год, «5 с.» — страница).

Все фиксеры работают в пределах одного TextRun: если матч пересекает
границу run-ов — пропускаем, чтобы не сломать форматирование.
Каждый фиксер локально импортирует регекс из соответствующей проверки
(single source of truth), поэтому чинит ровно то, что проверка находит.
"""

from __future__ import annotations

import re

from gostforge.model import (
    Block,
    Document,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import FixApplied, register

# Неразрывный пробел (U+00A0).
_NBSP = " "


def _iter_paragraphs(items: list[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph из списка вложенных элементов модели."""
    result: list[Paragraph] = []
    for item in items:
        if isinstance(item, Paragraph):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_paragraphs(item.children))
    return result


def _all_paragraphs(document: Document) -> list[Paragraph]:
    """Все Paragraph из всех PageSection документа (рекурсивный обход)."""
    paragraphs: list[Paragraph] = []
    for section in document.page_sections:
        paragraphs.extend(_iter_paragraphs(section.content))
    return paragraphs


def _text_runs(paragraph: Paragraph) -> list[TextRun]:
    """Только TextRun-ы из содержимого параграфа (CrossRef отфильтровываются)."""
    return [el for el in paragraph.content if isinstance(el, TextRun)]


def _paragraph_location(paragraph: Paragraph) -> str:
    """Стандартный путь в модели для FixApplied.location."""
    return f"paragraph[{paragraph.id}]"


@register("U.01")
def fix_si_unit_nbsp(document: Document, profile: Profile) -> list[FixApplied]:
    """Заменить обычный пробел между числом и единицей СИ на NBSP (U.01).

    Использует тот же паттерн, что и проверка U.01, поэтому исправляет
    ровно то, что она находит (единицы по ГОСТ Р 8.000-2015). Работает
    в пределах одного TextRun; видимо текст не меняется.
    """
    _ = profile
    from gostforge.validator.checks.units import _RE_REGULAR_SPACE_BEFORE_UNIT

    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        paragraph_changed = False
        for run in _text_runs(paragraph):
            if not run.text:
                continue
            new_text = _RE_REGULAR_SPACE_BEFORE_UNIT.sub(rf"\1{_NBSP}\3", run.text)
            if new_text != run.text:
                run.text = new_text
                paragraph_changed = True
        if paragraph_changed:
            applied.append(
                FixApplied(
                    fixer_code="U.01",
                    location=_paragraph_location(paragraph),
                    description=(
                        "Обычные пробелы между числом и единицей измерения (СИ) "
                        "заменены на неразрывные"
                    ),
                )
            )
    return applied


@register("U.02")
def fix_u02_punct_before_unit(document: Document, profile: Profile) -> list[FixApplied]:
    """Заменить «N.unit» / «N,unit» на «N<NBSP>unit» (U.02).

    Зеркально проверке U.02: пунктуация между числом и единицей СИ
    запрещена, должен быть (неразрывный) пробел. Если матч пересекает
    границу TextRun-ов — пропускаем, чтобы не ломать форматирование.

    Использует регекс проверки `_RE_PUNCT_BEFORE_UNIT` как единственный
    источник истины.
    """
    _ = profile
    from gostforge.validator.checks.units import _RE_PUNCT_BEFORE_UNIT

    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        paragraph_changed = False
        for run in _text_runs(paragraph):
            if not run.text:
                continue
            # Заменяем «N{punct}{unit}» на «N{NBSP}{unit}». Регекс из
            # проверки имеет группы: 1 — число, 2 — знак, 3 — единица.
            new_text = _RE_PUNCT_BEFORE_UNIT.sub(rf"\1{_NBSP}\3", run.text)
            if new_text != run.text:
                run.text = new_text
                paragraph_changed = True
        if paragraph_changed:
            applied.append(
                FixApplied(
                    fixer_code="U.02",
                    location=_paragraph_location(paragraph),
                    description=(
                        "Знак препинания между числом и единицей измерения "
                        "заменён на неразрывный пробел"
                    ),
                )
            )
    return applied


@register("U.03")
def fix_u03_unit_trailing_dot(document: Document, profile: Profile) -> list[FixApplied]:
    """Убрать точку после единицы измерения СИ (U.03).

    Зеркально проверке U.03 с теми же исключениями:
    * «1990 г.» — это год, точку оставляем;
    * «5 с.» — это «страница» в библиографии, пропускаем полностью.

    Работает в пределах одного TextRun. Использует регекс проверки
    `_RE_UNIT_WITH_TRAILING_DOT` как единственный источник истины.
    """
    _ = profile
    from gostforge.validator.checks.units import _RE_UNIT_WITH_TRAILING_DOT

    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        paragraph_changed = False
        for run in _text_runs(paragraph):
            if not run.text:
                continue
            # Контекстно решаем по каждому матчу: для «г»/«с» — проверка
            # на исключение «год»/«страница»; для остального — стрипаем точку.
            new_text, run_changed = _strip_trailing_dot_in_run(run.text, _RE_UNIT_WITH_TRAILING_DOT)
            if run_changed:
                run.text = new_text
                paragraph_changed = True
        if paragraph_changed:
            applied.append(
                FixApplied(
                    fixer_code="U.03",
                    location=_paragraph_location(paragraph),
                    description=(
                        "Удалена точка после единицы измерения (кроме исключений «год»/«страница»)"
                    ),
                )
            )
    return applied


def _strip_trailing_dot_in_run(text: str, regex: re.Pattern[str]) -> tuple[str, bool]:
    """Убрать точку после единицы измерения в `text`, повторяя исключения U.03.

    Возвращает (new_text, changed). Логика повторяет проверку:
    * unit == 'с' — всегда пропускаем (страница);
    * unit == 'г' и число >= 1500 — пропускаем (год).
    """
    parts: list[str] = []
    last_end = 0
    changed = False
    for match in regex.finditer(text):
        num_space = match.group(1)
        unit = match.group(2)
        # Исключения (симметричные проверке U.03).
        if unit == "с":
            continue
        if unit == "г":
            try:
                n = int(num_space.strip())
            except ValueError:
                n = -1
            if n >= 1500:
                # «1990 г.» — год, не «грамм».
                continue
        # Удаляем именно завершающую точку (group 3).
        parts.append(text[last_end : match.start(3)])
        last_end = match.end(3)
        changed = True
    if not changed:
        return text, False
    parts.append(text[last_end:])
    return "".join(parts), True


__all__ = [
    "fix_si_unit_nbsp",
    "fix_u02_punct_before_unit",
    "fix_u03_unit_trailing_dot",
]
