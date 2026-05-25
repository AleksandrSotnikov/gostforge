"""P.* — проверки приложений."""

# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

import re
from collections.abc import Sequence

from gostforge.model import (
    Document,
    InlineElement,
    LogicalSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# Шаблон: «Приложение X» в начале заголовка, X — одна буква.
# Допускаем заглавную или строчную, кириллическую или латинскую — это
# часть собственно проверки, которая решает, валидна ли буква.
_APPENDIX_HEADING_RE = re.compile(
    r"^\s*Приложение\s+([A-Za-zА-ЯЁа-яё])\b"
)

# Допустимый порядок русских заглавных букв для маркировки приложений
# (без Ё, З, Й, О, Ч, Ь, Ъ, Ы — по ГОСТ).
_ALLOWED_LETTERS: list[str] = list("АБВГДЕЖИКЛМНПРСТУФХЦШЩЭЮЯ")

# Дефолтный список запрещённых букв (русских заглавных). Может быть
# переопределён через `checks.P.01.params.forbidden_letters`.
_DEFAULT_FORBIDDEN_LETTERS: frozenset[str] = frozenset("ЁЗЙОЧЬЪЫ")


def _heading_text(content: Sequence[InlineElement]) -> str:
    """Склеить inline-содержимое заголовка в строку."""
    return "".join(el.text for el in content if isinstance(el, TextRun))


def _iter_logical_sections(
    items: Sequence[object],
) -> list[LogicalSection]:
    """Рекурсивно собрать все LogicalSection."""
    result: list[LogicalSection] = []
    for item in items:
        if isinstance(item, LogicalSection):
            result.append(item)
            result.extend(_iter_logical_sections(item.children))
    return result


def _all_logical_sections(document: Document) -> list[LogicalSection]:
    """Все LogicalSection документа."""
    sections: list[LogicalSection] = []
    for ps in document.page_sections:
        sections.extend(_iter_logical_sections(ps.content))
    return sections


@register("P.01")
def check_appendix_letter_marking(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Приложения должны маркироваться русскими заглавными буквами без запрещённых.

    Алгоритм:
    1. Найти LogicalSection.level==1 с заголовком «Приложение X».
    2. Для каждого X проверить:
       - X — русская буква (не латинская);
       - X — заглавная (не строчная);
       - X не входит в список запрещённых (по умолчанию Ё, З, Й, О, Ч,
         Ь, Ъ, Ы — легко путаются с цифрами и другими буквами);
       - X идёт в правильном порядке относительно других приложений
         (без пропусков по `_ALLOWED_LETTERS`).

    Параметры профиля (`checks.P.01.params`):
    - `forbidden_letters`: список запрещённых букв (по умолчанию
      см. `_DEFAULT_FORBIDDEN_LETTERS`).
    """
    violations: list[Violation] = []
    config = profile.checks.get("P.01")
    forbidden: frozenset[str] = _DEFAULT_FORBIDDEN_LETTERS
    if config and config.params.get("forbidden_letters"):
        custom = config.params["forbidden_letters"]
        if isinstance(custom, list):
            forbidden = frozenset(
                item.upper() for item in custom if isinstance(item, str)
            )

    # Собираем все приложения в порядке появления.
    found_letters: list[tuple[LogicalSection, str]] = []
    for section in _all_logical_sections(document):
        if section.level != 1:
            continue
        text = _heading_text(section.heading)
        match = _APPENDIX_HEADING_RE.match(text)
        if not match:
            continue
        letter = match.group(1)
        found_letters.append((section, letter))

    # Проверяем каждое приложение и собираем «валидные» буквы для
    # проверки порядка.
    valid_indices: list[tuple[LogicalSection, int]] = []
    for section, letter in found_letters:
        heading = _heading_text(section.heading).strip()
        # 1) латинская буква — отдельное нарушение.
        if not _is_cyrillic_letter(letter):
            violations.append(
                Violation(
                    check_code="P.01",
                    severity="error",
                    message=(
                        f"В заголовке «{heading}» приложение помечено "
                        f"латинской буквой «{letter}»; по ГОСТ приложения "
                        f"маркируются русскими заглавными буквами"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        f"Использовать русскую заглавную букву вместо «{letter}»"
                    ),
                    details={"section_id": section.id, "letter": letter},
                )
            )
            continue

        # 2) строчная — отдельное нарушение.
        upper = letter.upper()
        if letter != upper:
            violations.append(
                Violation(
                    check_code="P.01",
                    severity="error",
                    message=(
                        f"В заголовке «{heading}» приложение помечено "
                        f"строчной буквой «{letter}»; должна быть заглавная"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        f"Использовать заглавную букву «{upper}» вместо «{letter}»"
                    ),
                    details={"section_id": section.id, "letter": letter},
                )
            )
            continue

        # 3) запрещённая буква.
        if letter in forbidden:
            violations.append(
                Violation(
                    check_code="P.01",
                    severity="error",
                    message=(
                        f"В заголовке «{heading}» использована запрещённая "
                        f"буква «{letter}»; по ГОСТ нельзя использовать "
                        f"Ё, З, Й, О, Ч, Ь, Ъ, Ы"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        "Использовать другую русскую заглавную букву из "
                        "допустимого ряда: А, Б, В, Г, Д, Е, Ж, И, К, Л, М, "
                        "Н, П, Р, С, Т, У, Ф, Х, Ц, Ш, Щ, Э, Ю, Я"
                    ),
                    details={"section_id": section.id, "letter": letter},
                )
            )
            continue

        # 4) буква в списке допустимых — но если её там нет (например,
        # совсем редкая) — отметим как нарушение, чтобы быть строгими.
        try:
            idx = _ALLOWED_LETTERS.index(letter)
        except ValueError:
            violations.append(
                Violation(
                    check_code="P.01",
                    severity="error",
                    message=(
                        f"В заголовке «{heading}» буква «{letter}» не входит "
                        f"в допустимый ряд для маркировки приложений"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        "Использовать букву из допустимого ряда: А, Б, В, ..."
                    ),
                    details={"section_id": section.id, "letter": letter},
                )
            )
            continue
        valid_indices.append((section, idx))

    # 5) Проверка порядка: ожидаем 0, 1, 2, ... индексы в _ALLOWED_LETTERS.
    for expected, (section, idx) in enumerate(valid_indices):
        if idx == expected:
            continue
        heading = _heading_text(section.heading).strip()
        expected_letter = _ALLOWED_LETTERS[expected]
        actual_letter = _ALLOWED_LETTERS[idx]
        violations.append(
            Violation(
                check_code="P.01",
                severity="error",
                message=(
                    f"Нарушен порядок маркировки приложений: ожидалось "
                    f"«Приложение {expected_letter}», найдено "
                    f"«Приложение {actual_letter}» в заголовке «{heading}»"
                ),
                location=f"page_sections.*.logical_section[{section.id}]",
                suggestion=(
                    f"Переименовать приложение в «Приложение "
                    f"{expected_letter}» или добавить пропущенные "
                    f"приложения"
                ),
                details={
                    "section_id": section.id,
                    "expected": expected_letter,
                    "found": actual_letter,
                },
            )
        )
        # Остановимся на первом несоответствии, чтобы не плодить
        # каскад нарушений.
        break

    return violations


def _is_cyrillic_letter(letter: str) -> bool:
    """True, если `letter` — одна кириллическая буква."""
    if len(letter) != 1:
        return False
    code = ord(letter)
    # Кириллица: U+0400..U+04FF; ё в U+0451, Ё в U+0401.
    return 0x0400 <= code <= 0x04FF


__all__ = [
    "check_appendix_letter_marking",
]
