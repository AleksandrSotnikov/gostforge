"""P.* — проверки приложений."""

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


# --- P.02, P.03, P.04, P.05 — вспомогательные хелперы --------------------


# Любой потенциальный заголовок приложения — начинается со слова «Приложение».
# Используется в P.02..P.05 для отбора секций-приложений.
_APPENDIX_PREFIX_RE = re.compile(r"^\s*Приложение\b", re.IGNORECASE)

# Строгий формат заголовка приложения (P.04):
# - точно «Приложение» с заглавной;
# - один пробел (или несколько);
# - одна РУССКАЯ ЗАГЛАВНАЯ буква;
# - после неё либо точка с пробелом и текстом, либо конец строки (опционально
#   допускаем пробел и далее — содержательный заголовок).
_STRICT_APPENDIX_HEADING_RE = re.compile(
    r"^Приложение\s+([А-Я])(?:\s+\S.*|\.\s+\S.*|$)"
)


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


def _appendix_sections(document: Document) -> list[LogicalSection]:
    """Все LogicalSection level=1, чей заголовок начинается с «Приложение»."""
    result: list[LogicalSection] = []
    for section in _all_logical_sections(document):
        if section.level != 1:
            continue
        text = _heading_text(section.heading)
        if _APPENDIX_PREFIX_RE.match(text):
            result.append(section)
    return result


def _appendix_letter(heading: str) -> str | None:
    """Извлечь букву приложения из заголовка (или None, если не получилось)."""
    match = _APPENDIX_HEADING_RE.match(heading)
    if not match:
        return None
    return match.group(1)


def _first_paragraph_of_section(section: LogicalSection) -> Paragraph | None:
    """Найти первый Paragraph среди прямых детей раздела."""
    for child in section.children:
        if isinstance(child, Paragraph):
            return child
    return None


# --- P.02 ------------------------------------------------------------------


def _has_appendix_reference(text: str, letter: str) -> bool:
    """Есть ли в тексте ссылка на приложение `letter`."""
    # Экранируем letter (одна буква, но на всякий случай).
    safe = re.escape(letter)
    patterns = [
        rf"см\.\s+приложении\s+{safe}\b",
        rf"см\.\s+приложение\s+{safe}\b",
        rf"в\s+приложении\s+{safe}\b",
        rf"\(приложение\s+{safe}\)",
        rf"\(прил\.\s*{safe}\)",
        rf"\bприл\.\s*{safe}\b",
        rf"\bприложение\s+{safe}\b",
        rf"\bприложении\s+{safe}\b",
        rf"\bприложения\s+{safe}\b",
        rf"\bприложений\s+{safe}\b",
    ]
    return any(re.search(pat, text, re.IGNORECASE) for pat in patterns)


@register("P.02")
def check_appendix_referenced(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """На каждое приложение должна быть ссылка в основном тексте.

    Алгоритм:
    1. Собрать все LogicalSection.level==1 с заголовком «Приложение X».
    2. Собрать весь текст Paragraph документа (включая основной текст
       и текст внутри других приложений — последнее не страшно, ссылок
       из одного приложения на другое обычно мало).
    3. Для каждой буквы приложения — искать в тексте ссылку шаблонов
       «см. приложение X», «в приложении X», «(приложение X)»,
       «прил. X» (case-insensitive).
    4. Если не нашли — Violation.
    """
    _ = profile
    violations: list[Violation] = []
    appendices = _appendix_sections(document)
    if not appendices:
        return violations

    # Соберём общий текст всех Paragraph.
    paragraphs_text = "\n".join(
        _paragraph_text(p) for p in _all_paragraphs(document)
    )

    for section in appendices:
        heading = _heading_text(section.heading).strip()
        letter = _appendix_letter(heading)
        if letter is None:
            # Если буква не извлеклась — это случай P.04, P.02 пропускает.
            continue
        if _has_appendix_reference(paragraphs_text, letter):
            continue
        violations.append(
            Violation(
                check_code="P.02",
                severity="error",
                message=(
                    f"В тексте отсутствует ссылка на «Приложение {letter}» "
                    f"(заголовок «{heading}»)"
                ),
                location=f"page_sections.*.logical_section[{section.id}]",
                suggestion=(
                    f"Добавить в основной текст явную ссылку, например: "
                    f"«см. приложение {letter}» или «(приложение {letter})»"
                ),
                details={"section_id": section.id, "letter": letter},
            )
        )

    return violations


# --- P.03 ------------------------------------------------------------------


@register("P.03")
def check_appendix_page_break(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждое приложение должно начинаться с новой страницы.

    Это «локальная» версия S.06 для разделов-приложений: проверяем
    у первого Paragraph внутри section.children, что
    `page_break_before` НЕ равен False.

    Семантика повторяет S.06 — `None` не считаем нарушением, потому что
    разрыв может быть задан через Word-стиль заголовка.
    """
    _ = profile
    violations: list[Violation] = []
    appendices = _appendix_sections(document)
    for section in appendices:
        first_para = _first_paragraph_of_section(section)
        if first_para is None:
            continue
        if first_para.page_break_before is False:
            heading = _heading_text(section.heading).strip()
            violations.append(
                Violation(
                    check_code="P.03",
                    severity="error",
                    message=(
                        f"Приложение «{heading}» не начинается с новой страницы"
                    ),
                    location=f"page_sections.*.logical_section[{section.id}]",
                    suggestion=(
                        "Включить разрыв страницы перед заголовком приложения "
                        "(Word: «Разрыв страницы перед» в свойствах абзаца)"
                    ),
                    details={"section_id": section.id},
                )
            )
    return violations


# --- P.04 ------------------------------------------------------------------


@register("P.04")
def check_appendix_heading_format(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Формат заголовка приложения: «Приложение X», где X — русская заглавная буква.

    После «X» может следовать пробел и содержательный заголовок («ПРИМЕР
    МЕТОДИКИ»), либо точка с пробелом и содержательный заголовок, либо
    конец строки. Дополнительные символы (например, скобки или цифры
    вместо буквы) — нарушение.
    """
    _ = profile
    violations: list[Violation] = []
    appendices = _appendix_sections(document)
    for section in appendices:
        heading = _heading_text(section.heading).strip()
        if _STRICT_APPENDIX_HEADING_RE.match(heading):
            continue
        violations.append(
            Violation(
                check_code="P.04",
                severity="warning",
                message=(
                    f"Заголовок «{heading}» не соответствует формату "
                    f"«Приложение X», где X — русская заглавная буква"
                ),
                location=f"page_sections.*.logical_section[{section.id}]",
                suggestion=(
                    "Привести заголовок к виду «Приложение А», «Приложение Б» "
                    "и т.д. (русская заглавная буква, без латиницы и цифр)"
                ),
                details={"section_id": section.id, "heading": heading},
            )
        )
    return violations


# --- P.05 ------------------------------------------------------------------


def _is_meaningful_title_paragraph(paragraph: Paragraph) -> bool:
    """Эвристика: является ли параграф «содержательным заголовком».

    Признаки:
    - style_name начинается с "Heading" (Heading 1..9, Heading 2 и т.п.);
    - либо хотя бы один TextRun имеет bold=True.
    """
    style = paragraph.style_name or ""
    if style.startswith("Heading"):
        return True
    return any(
        isinstance(el, TextRun) and el.bold is True for el in paragraph.content
    )


@register("P.05")
def check_appendix_has_content_title(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """У каждого приложения второй строкой должен идти содержательный заголовок.

    Эвристика: первый Paragraph в children должен либо иметь
    style_name, начинающийся с "Heading", либо содержать хотя бы один
    TextRun с bold=True.

    Если параграфов в приложении вообще нет — пропускаем (Violation
    в P.03 обычно).
    """
    _ = profile
    violations: list[Violation] = []
    appendices = _appendix_sections(document)
    for section in appendices:
        first_para = _first_paragraph_of_section(section)
        if first_para is None:
            continue
        if _is_meaningful_title_paragraph(first_para):
            continue
        heading = _heading_text(section.heading).strip()
        violations.append(
            Violation(
                check_code="P.05",
                severity="warning",
                message=(
                    f"У приложения «{heading}» отсутствует содержательный "
                    f"заголовок (вторая строка должна быть в стиле "
                    f"«Заголовок 2» или с полужирным начертанием)"
                ),
                location=f"page_sections.*.logical_section[{section.id}]",
                suggestion=(
                    "Добавить второй строкой содержательный заголовок (например, "
                    "«ПРИМЕР МЕТОДИКИ РАСЧЁТА») в стиле Heading 2 или полужирным"
                ),
                details={"section_id": section.id},
            )
        )
    return violations


__all__ = [
    "check_appendix_has_content_title",
    "check_appendix_heading_format",
    "check_appendix_letter_marking",
    "check_appendix_page_break",
    "check_appendix_referenced",
]
