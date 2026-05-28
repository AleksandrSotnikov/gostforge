"""U.* — проверки единиц измерения (ГОСТ Р 8.000-2015 СИ).

Покрывает требования к написанию физических единиц:
* U.01 — между числом и единицей неразрывный пробел («10 кг», не «10кг»).
* U.02 — единицы не отделяются от числа точкой или запятой
  («10 % не «10.%»).
* U.03 — единицы пишутся согласно стандарту (без точки в конце:
  «кг» не «кг.», «°C» не «°С»).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# Список стандартных единиц измерения СИ (русские и латинские
# написания). Используется для определения паттерна «число + единица».
_SI_UNITS = (
    # Длина
    "мм",
    "см",
    "дм",
    "м",
    "км",
    "нм",
    "мкм",
    "mm",
    "cm",
    "m",
    "km",
    # Масса
    "мкг",
    "мг",
    "г",
    "кг",
    "т",
    "g",
    "kg",
    "t",
    # Время
    "мс",
    "мкс",
    "нс",
    "с",
    "мин",
    "ч",
    "сут",
    "ms",
    "s",
    "min",
    "h",
    # Площадь и объём
    "м²",
    "м³",
    "см²",
    "см³",
    "л",
    "мл",
    # Электрические
    "В",
    "мВ",
    "кВ",
    "А",
    "мА",
    "Ом",
    "Ω",
    "Вт",
    "кВт",
    "МВт",
    "V",
    "mV",
    "kV",
    "A",
    "mA",
    "W",
    "kW",
    "MW",
    # Температура
    "°C",
    "°F",
    "K",
    "°К",
    # Давление
    "Па",
    "кПа",
    "МПа",
    "ГПа",
    "бар",
    "атм",
    "Pa",
    "kPa",
    "MPa",
    "bar",
    "atm",
    # Частота
    "Гц",
    "кГц",
    "МГц",
    "ГГц",
    "Hz",
    "kHz",
    "MHz",
    "GHz",
    # Информатика
    "бит",
    "Б",
    "кБ",
    "МБ",
    "ГБ",
    "ТБ",
    "bit",
    "B",
    "KB",
    "MB",
    "GB",
    "TB",
    # Проценты и доли
    "%",
    "‰",
    "ppm",
    # Углы
    "°",
    "рад",
    "град",
)

# Распознаваемые «нестандартные» написания, которые должны быть приведены
# к канонической форме (U.03).
_UNIT_NORMALIZATIONS: dict[str, str] = {
    # Точка в конце: «кг.» → «кг», «м.» → «м» (для единиц СИ).
    "кг.": "кг",
    "м.": "м",
    "г.": "г",  # внимание: 'г.' может быть «год» — обрабатываем контекстно
    "с.": "с",  # 'с.' = «страница», тоже контекстно
    # Старые написания единиц.
    "сек": "с",
    "мин.": "мин",
    "час": "ч",
    "час.": "ч",
}


def _iter_paragraphs(items: Sequence[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph документа."""
    result: list[Paragraph] = []
    for item in items:
        if isinstance(item, Paragraph):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_paragraphs(item.children))
    return result


def _all_paragraphs(document: Document) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for section in document.page_sections:
        paragraphs.extend(_iter_paragraphs(section.content))
    return paragraphs


def _paragraph_text(paragraph: Paragraph) -> str:
    return "".join(el.text for el in paragraph.content if isinstance(el, TextRun))


def _preview(text: str, limit: int = 50) -> str:
    text = text.strip()
    return text[:limit] + ("…" if len(text) > limit else "")


# U.01: число + (обычный пробел) + единица. Должен быть неразрывный
# пробел (U+00A0). Регекс ищет «число + ОБЫЧНЫЙ пробел + единица СИ».
# Единицы сортируем по длине убывания, чтобы 'кВт' матчился раньше 'В'.
_UNITS_BY_LENGTH = sorted(_SI_UNITS, key=len, reverse=True)
_UNITS_REGEX = "|".join(re.escape(u) for u in _UNITS_BY_LENGTH)
# Граница после единицы — пробел, знак, конец строки. Чтобы не схватить
# часть слова (например 'мс' не должен совпасть в «вместе»).
_BOUNDARY = r"(?=[\s.,;:!?)\]/-]|$)"

_RE_REGULAR_SPACE_BEFORE_UNIT = re.compile(
    r"(\d+)( )(" + _UNITS_REGEX + r")" + _BOUNDARY,
)

# U.02: число + знак (запятая/точка) + единица — недопустимо.
_RE_PUNCT_BEFORE_UNIT = re.compile(
    r"(\d+)([.,])(" + _UNITS_REGEX + r")" + _BOUNDARY,
)

# U.03: единица с точкой в конце (для базовых единиц СИ).
# Сложный кейс: 'г.', 'с.' могут быть «год», «страница» — контекст.
_RE_UNIT_WITH_TRAILING_DOT = re.compile(
    r"(\d+\s?)(" + _UNITS_REGEX + r")(\.)" + _BOUNDARY,
)


@register("U.01")
def check_nbsp_between_number_and_unit(document: Document, profile: Profile) -> list[Violation]:
    """Между числом и единицей измерения должен быть неразрывный пробел.

    По ГОСТ Р 8.000-2015 (СИ) число и обозначение единицы пишутся через
    пробел, который не должен разрываться при переносе строки.
    OOXML — неразрывный пробел U+00A0.

    Срабатывает только на обычный пробел (U+0020) — неразрывный (U+00A0)
    не нарушает правило.
    """
    _ = profile
    violations: list[Violation] = []
    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _RE_REGULAR_SPACE_BEFORE_UNIT.finditer(text):
            num = match.group(1)
            unit = match.group(3)
            violations.append(
                Violation(
                    check_code="U.01",
                    severity="warning",
                    message=(
                        f"«{num} {unit}» в абзаце «{_preview(text)}» — "
                        f"обычный пробел между числом и единицей; "
                        f"должен быть неразрывный пробел"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        "Заменить пробел между числом и единицей на "
                        "неразрывный (Ctrl+Shift+Space в Word)"
                    ),
                    details={
                        "paragraph_id": paragraph.id,
                        "number": num,
                        "unit": unit,
                    },
                )
            )
    return violations


@register("U.02")
def check_no_punctuation_before_unit(document: Document, profile: Profile) -> list[Violation]:
    """Между числом и единицей не должно быть знака препинания.

    Запрещено: «10.кг», «50,%», «20.°C».
    Допустимо: «10 кг», «50 %» (с пробелом, через U.01).
    """
    _ = profile
    violations: list[Violation] = []
    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _RE_PUNCT_BEFORE_UNIT.finditer(text):
            num = match.group(1)
            punct = match.group(2)
            unit = match.group(3)
            violations.append(
                Violation(
                    check_code="U.02",
                    severity="error",
                    message=(
                        f"«{num}{punct}{unit}» в абзаце «{_preview(text)}» — "
                        f"между числом и единицей не должно быть «{punct}»"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(f"Заменить на «{num} {unit}» (с неразрывным пробелом)"),
                    details={
                        "paragraph_id": paragraph.id,
                        "punct": punct,
                        "unit": unit,
                    },
                )
            )
    return violations


@register("U.03")
def check_unit_no_trailing_dot(document: Document, profile: Profile) -> list[Violation]:
    """Единицы измерения СИ пишутся без точки в конце.

    Допустимо: «10 кг», «20 м», «5 с».
    Недопустимо: «10 кг.», «20 м.».

    Исключения (НЕ единицы, а сокращения):
    * «г.» = год;
    * «с.» = страница;
    * «гг.» = годы.
    Эти случаи распознаются контекстно: «г.» после года-как-числа,
    «с.» в библиографической ссылке.
    """
    _ = profile
    violations: list[Violation] = []
    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _RE_UNIT_WITH_TRAILING_DOT.finditer(text):
            num_space = match.group(1)
            unit = match.group(2)
            # Защита от ложных срабатываний.
            # Если unit ∈ {'г', 'с'} — это может быть «год» или «страница».
            # Грубая эвристика: если число большое (>1500), 'г.' — это год.
            if unit in {"г", "с"}:
                try:
                    n = int(num_space.strip())
                    if unit == "г" and n >= 1500:
                        # «1990 г.» — это год.
                        continue
                except ValueError:
                    pass
                # Для «с.» в библиографии — слишком много ложных
                # срабатываний; пропускаем.
                if unit == "с":
                    continue
            violations.append(
                Violation(
                    check_code="U.03",
                    severity="warning",
                    message=(
                        f"«{num_space}{unit}.» в абзаце «{_preview(text)}» — "
                        f"точка после единицы измерения «{unit}» не ставится"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(f"Заменить «{unit}.» на «{unit}»"),
                    details={
                        "paragraph_id": paragraph.id,
                        "unit": unit,
                    },
                )
            )
    return violations


__all__ = [
    "check_nbsp_between_number_and_unit",
    "check_no_punctuation_before_unit",
    "check_unit_no_trailing_dot",
]
