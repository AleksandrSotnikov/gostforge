# ruff: noqa: RUF001, RUF002, RUF003

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
    Paragraph,
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

# Шаблон для извлечения верхнего номера раздела (без подуровней),
# например «1 Введение» → 1, «1.2 Анализ» → 1, «1. Введение» → 1.
_LEADING_NUMBER = re.compile(r"^(\d+)(?:\.\d+)*\.?\s")


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


@register("H.02")
def check_heading_2_format(document: Document, profile: Profile) -> list[Violation]:
    """Проверка формата заголовков 2 уровня.

    Сверяется с `profile.styles.extra.heading_2` (font, size_pt, bold,
    uppercase). Если у заголовка свойство явно задано и не совпадает с
    эталоном — нарушение. None означает «наследуется» — пропускаем.
    """
    violations: list[Violation] = []
    heading_2: dict[str, Any] = profile.styles.extra.get("heading_2", {}) or {}

    expected_font: str | None = heading_2.get("font")
    expected_size: float | None = heading_2.get("size_pt")
    expected_bold: bool | None = heading_2.get("bold")
    expected_uppercase: bool | None = heading_2.get("uppercase")

    for section in _all_logical_sections(document):
        if section.level != 2:
            continue

        text = _heading_text(section.heading)
        runs = _heading_runs(section.heading)

        if expected_uppercase is True and text and text != text.upper():
            violations.append(
                _violation(
                    "H.02",
                    f"Заголовок 2 уровня «{text}» должен быть в верхнем регистре",
                    section.id,
                    suggestion="Привести заголовок к верхнему регистру",
                )
            )

        for run in runs:
            if not run.text or not run.text.strip():
                continue
            if expected_font and run.font and run.font != expected_font:
                violations.append(
                    _violation(
                        "H.02",
                        f"В заголовке 2 уровня «{text}» использован шрифт "
                        f"«{run.font}» вместо «{expected_font}»",
                        section.id,
                        suggestion=f"Использовать шрифт «{expected_font}» в заголовках 2 уровня",
                    )
                )
            if (
                expected_size is not None
                and run.size_pt is not None
                and abs(run.size_pt - float(expected_size)) > _SIZE_TOLERANCE_PT
            ):
                violations.append(
                    _violation(
                        "H.02",
                        f"В заголовке 2 уровня «{text}» использован кегль "
                        f"{run.size_pt} pt вместо {expected_size} pt",
                        section.id,
                        suggestion=f"Использовать кегль {expected_size} pt в заголовках 2 уровня",
                    )
                )
            if expected_bold is True and run.bold is False:
                violations.append(
                    _violation(
                        "H.02",
                        f"Заголовок 2 уровня «{text}» не выделен полужирным",
                        section.id,
                        suggestion="Сделать заголовок полужирным",
                    )
                )

    return violations


@register("H.03")
def check_heading_number_no_trailing_dot(
    document: Document, profile: Profile
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


@register("H.08")
def check_heading_no_terminal_punctuation(
    document: Document, profile: Profile
) -> list[Violation]:
    """Заголовок не должен оканчиваться точкой (или многоточием).

    По ГОСТ Р 2.105-2019 заголовок не должен оканчиваться знаком
    препинания, кроме `:` или `?`. На Фазе 1 проверяем только точку и
    многоточие (`.`, `...`, `…`). Severity=warning.
    """
    violations: list[Violation] = []
    for section in _all_logical_sections(document):
        text = _heading_text(section.heading).rstrip()
        if not text:
            continue
        # Многоточие в виде Unicode-символа или трёх точек.
        if text.endswith("…") or text.endswith("...") or text.endswith("."):
            violations.append(
                Violation(
                    check_code="H.08",
                    severity="warning",
                    message=(
                        f"Заголовок «{text}» оканчивается точкой/многоточием — "
                        f"по ГОСТ Р 2.105-2019 не допускается"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}].heading",
                    suggestion="Убрать точку в конце заголовка",
                )
            )
    return violations


@register("H.04")
def check_heading_numbering_continuous(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Нумерация разделов 1 уровня не должна иметь пропусков.

    Семантика (Фаза 1):
    - Берутся все LogicalSection level==1 в порядке появления.
    - Если ни один не нумерован — проверка ничего не делает.
    - Если ВСЕ нумерованы — проверяется последовательность 1, 2, 3, ...
      На первый «выпадающий» номер — Violation (severity=error).
    - Граничный случай (часть нумерованы, часть — нет) — Violation
      severity=warning «используйте единый стиль».
    """
    violations: list[Violation] = []
    level1: list[LogicalSection] = []
    for ps in document.page_sections:
        level1.extend(s for s in iter_logical_sections(ps.content) if s.level == 1)

    if not level1:
        return violations

    numbered: list[tuple[LogicalSection, int]] = []
    unnumbered: list[LogicalSection] = []
    for section in level1:
        text = _heading_text(section.heading).lstrip()
        match = _LEADING_NUMBER.match(text)
        if match:
            try:
                numbered.append((section, int(match.group(1))))
            except ValueError:
                unnumbered.append(section)
        else:
            unnumbered.append(section)

    if not numbered:
        # Никто не нумерован — валидный сценарий (нумерации нет).
        return violations

    if unnumbered:
        # Смешанный стиль — мягкое предупреждение.
        first_un = unnumbered[0]
        first_num_text = _heading_text(numbered[0][0].heading).strip()
        violations.append(
            Violation(
                check_code="H.04",
                severity="warning",
                message=(
                    f"Часть заголовков 1 уровня нумерованы, часть — нет; "
                    f"используйте единый стиль (например, «{_heading_text(first_un.heading).strip()}» "
                    f"без номера, а «{first_num_text}» — с номером)"
                ),
                location=f"page_sections.*.logical_section[{first_un.id}]",
                suggestion=(
                    "Принять единый стиль: либо нумеровать все разделы 1 уровня, "
                    "либо ни один"
                ),
                details={"section_id": first_un.id},
            )
        )
        return violations

    # Все нумерованы — проверяем 1, 2, 3, ...
    expected = 1
    for section, num in numbered:
        if num != expected:
            heading = _heading_text(section.heading).strip()
            violations.append(
                Violation(
                    check_code="H.04",
                    severity="error",
                    message=(
                        f"Нумерация разделов нарушена: после {expected - 1} "
                        f"ожидается {expected}, найдено {num} (заголовок «{heading}»)"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        f"Перенумеровать раздел: «{expected} ...» вместо «{num} ...»"
                    ),
                    details={
                        "section_id": section.id,
                        "expected": str(expected),
                        "found": str(num),
                    },
                )
            )
            # Остановимся на первом выпадающем — дальше всё равно сместится.
            break
        expected += 1

    return violations


@register("H.05")
def check_heading_hierarchy(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Иерархия заголовков не должна иметь пропусков уровней.

    Например, недопустимо: после level=1 сразу level=3 (минуя level=2).
    """
    violations: list[Violation] = []
    sections: list[LogicalSection] = []
    for ps in document.page_sections:
        sections.extend(iter_logical_sections(ps.content))

    prev_section: LogicalSection | None = None
    for section in sections:
        if prev_section is not None and section.level > prev_section.level + 1:
            cur_text = _heading_text(section.heading).strip()
            prev_text = _heading_text(prev_section.heading).strip()
            missing = prev_section.level + 1
            violations.append(
                Violation(
                    check_code="H.05",
                    severity="error",
                    message=(
                        f"Заголовок «{cur_text}» (уровень {section.level}) "
                        f"идёт сразу после заголовка «{prev_text}» "
                        f"(уровень {prev_section.level}) — пропущен уровень {missing}"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        f"Добавьте промежуточный заголовок уровня {missing} "
                        f"или понизьте уровень «{cur_text}» до {missing}"
                    ),
                    details={
                        "section_id": section.id,
                        "level": str(section.level),
                        "prev_level": str(prev_section.level),
                    },
                )
            )
        prev_section = section

    return violations


@register("H.06")
def check_heading_not_hanging(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Заголовок не должен «висеть» внизу страницы без содержимого.

    Полноценная проверка требует свойства `keep_with_next` (`<w:keepNext/>`)
    у параграфа-заголовка — оно склеивает заголовок со следующим блоком и
    предотвращает «висячий» заголовок. На Фазе 2 парсер этого свойства не
    сохраняет, поэтому реализуется ослабленная эвристика:

    Если у LogicalSection нет children — заголовок не имеет за собой никакого
    содержимого, что в Word интерпретируется как висячий. Severity=warning.

    Также сообщаем, если первый дочерний блок — пустой Paragraph (есть
    содержимое, но фактически пустое).
    """
    violations: list[Violation] = []
    for section in _all_logical_sections(document):
        text = _heading_text(section.heading).strip()
        if not text:
            # Без заголовка проверять нечего.
            continue

        if not section.children:
            violations.append(
                Violation(
                    check_code="H.06",
                    severity="warning",
                    message=(
                        f"Заголовок «{text}» не имеет следующего за ним "
                        f"содержимого и может «висеть» внизу страницы"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        "Добавьте текст под заголовком или установите свойство "
                        "«не отрывать от следующего» (keep with next)"
                    ),
                    details={"section_id": section.id},
                )
            )
            continue

        # Проверим, что первый дочерний блок — не пустой Paragraph.
        first = section.children[0]
        if isinstance(first, Paragraph):
            inline_text = "".join(
                el.text for el in first.content if isinstance(el, TextRun)
            ).strip()
            if not inline_text:
                violations.append(
                    Violation(
                        check_code="H.06",
                        severity="warning",
                        message=(
                            f"После заголовка «{text}» идёт пустой абзац — "
                            f"заголовок может «висеть» внизу страницы"
                        ),
                        location=f"page_sections.*.logical_section[{section.id}]",
                        suggestion=(
                            "Удалите пустой абзац или добавьте под заголовком "
                            "осмысленный текст"
                        ),
                        details={"section_id": section.id},
                    )
                )

    return violations


@register("H.07")
def check_heading_spacing(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Отступы до и после заголовка (заглушка).

    Параметры из `profile.styles.extra.heading_1` и `heading_2`:
    - `spacing_before_pt: float` (например 18)
    - `spacing_after_pt: float` (например 12)

    TODO (Фаза 2): в текущей модели у Paragraph нет полей
    `spacing_before_pt` / `spacing_after_pt` — они хранятся в стилях Word.
    Кроме того, в LogicalSection.heading — это `list[InlineElement]`, а не
    Paragraph, у которого можно было бы прочитать отступы. Полноценная
    реализация требует расширения модели и парсера.
    """
    return []


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
    "check_heading_2_format",
    "check_heading_hierarchy",
    "check_heading_no_terminal_punctuation",
    "check_heading_not_hanging",
    "check_heading_number_no_trailing_dot",
    "check_heading_numbering_continuous",
    "check_heading_spacing",
    "iter_logical_sections",
]
