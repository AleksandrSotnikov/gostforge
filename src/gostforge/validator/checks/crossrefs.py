"""C.* — проверки перекрёстных ссылок.

Проверки направления «текст → объект»: каждая ссылка в тексте должна
указывать на существующий объект (рисунок, таблицу, источник).

Сравнение с I.06/B.08 — там обратное направление: на каждый объект
должна быть ссылка в тексте; здесь же каждая ссылка должна вести к
существующему объекту.
"""

# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

import re
from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    Figure,
    Formula,
    InlineElement,
    LogicalSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# --- Хелперы ----------------------------------------------------------------

_PREVIEW_LIMIT = 80


def _iter_paragraphs(items: Sequence[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph (через LogicalSection.children).

    Подписи рисунков/таблиц в `Figure.caption` / `Table.caption` сюда не
    попадают: они хранятся как `list[InlineElement]`, а не Paragraph.
    """
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


def _caption_text(elements: Sequence[InlineElement]) -> str:
    """Склеить подпись в строку (только TextRun)."""
    return "".join(el.text for el in elements if isinstance(el, TextRun)).strip()


# --- C.01 — ссылки на рисунки разрешаются ----------------------------------


# Извлечь номер из подписи рисунка: «Рисунок 1 — Название», «Рис. 2».
_FIGURE_NUMBER_RE = re.compile(r"^Рис(?:унок)?\.?\s+(\d+)")

# Поиск в тексте ссылки на рисунок N (case-insensitive).
# Принимаем: «рисунок 1», «рисунке 1», «рисунков 1», «рисунках 1»,
# «рис. 1», «рис 1», в т.ч. с предшествующим «см.».
_FIGURE_REF_RE = re.compile(
    r"(?:см\.\s+)?рис(?:унок|унке|унков|унках|унка|унку|унком)?\.?\s+(\d+)",
    re.IGNORECASE,
)


def _iter_figures(items: Sequence[LogicalSection | Block]) -> list[Figure]:
    """Рекурсивно собрать все Figure (через LogicalSection.children)."""
    result: list[Figure] = []
    for item in items:
        if isinstance(item, Figure):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_figures(item.children))
    return result


def _all_figures(document: Document) -> list[Figure]:
    """Все Figure документа (плоско, со всех PageSection)."""
    figures: list[Figure] = []
    for ps in document.page_sections:
        figures.extend(_iter_figures(ps.content))
    return figures


def _figure_numbers(document: Document) -> set[int]:
    """Собрать множество номеров рисунков из подписей."""
    numbers: set[int] = set()
    for figure in _all_figures(document):
        text = _caption_text(figure.caption)
        if not text:
            continue
        match = _FIGURE_NUMBER_RE.match(text)
        if not match:
            continue
        try:
            numbers.add(int(match.group(1)))
        except ValueError:
            continue
    return numbers


@register("C.01")
def check_figure_references_resolve(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая ссылка «(см.) рисунок N» в тексте должна указывать на существующий рисунок.

    Алгоритм:
    1. Собрать множество номеров рисунков из их подписей.
    2. Для каждого Paragraph документа найти все совпадения по шаблону
       `(?:см\\.\\s+)?рис(?:унок|унке|унков|унках)?\\.?\\s+(\\d+)`
       (case-insensitive).
    3. Если номер ссылки не входит в множество существующих — Violation.

    Подписи самих рисунков (Figure.caption) не учитываются, потому что
    при склейке текста учитываются только Paragraph'ы.
    """
    violations: list[Violation] = []
    existing = _figure_numbers(document)

    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _FIGURE_REF_RE.finditer(text):
            try:
                num = int(match.group(1))
            except ValueError:
                continue
            if num in existing:
                continue
            violations.append(
                Violation(
                    check_code="C.01",
                    severity="error",
                    message=(
                        f"Ссылка на рисунок {num} в абзаце «{_preview(text)}» "
                        f"не находит соответствующего рисунка"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        f"Проверить номер: рисунка {num} в документе нет. "
                        f"Возможно, опечатка в номере или забыли добавить рисунок."
                    ),
                    details={"paragraph_id": paragraph.id, "number": str(num)},
                )
            )

    return violations


# --- C.02 — ссылки на таблицы разрешаются ----------------------------------


_TABLE_NUMBER_RE = re.compile(r"^Таблица\s+(\d+)")

# Поиск в тексте ссылки на таблицу N (case-insensitive).
# Принимаем: «таблица 1», «таблице 1», «таблицу 1», «таблиц 1»,
# «таблицах 1», «табл. 1», «табл 1», в т.ч. с предшествующим «см.».
_TABLE_REF_RE = re.compile(
    r"(?:см\.\s+)?табл(?:ица|ице|ицу|иц|ицах|ицы)?\.?\s*(\d+)",
    re.IGNORECASE,
)


def _iter_tables(items: Sequence[LogicalSection | Block]) -> list[Table]:
    """Рекурсивно собрать все Table (через LogicalSection.children)."""
    result: list[Table] = []
    for item in items:
        if isinstance(item, Table):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_tables(item.children))
    return result


def _all_tables(document: Document) -> list[Table]:
    """Все Table документа (плоско, со всех PageSection)."""
    tables: list[Table] = []
    for ps in document.page_sections:
        tables.extend(_iter_tables(ps.content))
    return tables


def _table_numbers(document: Document) -> set[int]:
    """Собрать множество номеров таблиц из подписей."""
    numbers: set[int] = set()
    for table in _all_tables(document):
        text = _caption_text(table.caption)
        if not text:
            continue
        match = _TABLE_NUMBER_RE.match(text)
        if not match:
            continue
        try:
            numbers.add(int(match.group(1)))
        except ValueError:
            continue
    return numbers


@register("C.02")
def check_table_references_resolve(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая ссылка «(см.) таблицу N» в тексте должна указывать на существующую таблицу.

    Алгоритм:
    1. Собрать множество номеров таблиц из их подписей.
    2. Для каждого Paragraph найти все совпадения по шаблону
       `(?:см\\.\\s+)?табл(?:ица|.|ице|иц|ицу|ицах)?\\s*(\\d+)`
       (case-insensitive).
    3. Если номер ссылки не входит в множество существующих — Violation.

    Подписи самих таблиц (Table.caption) не учитываются, потому что при
    склейке текста учитываются только Paragraph'ы.
    """
    violations: list[Violation] = []
    existing = _table_numbers(document)

    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _TABLE_REF_RE.finditer(text):
            try:
                num = int(match.group(1))
            except ValueError:
                continue
            if num in existing:
                continue
            violations.append(
                Violation(
                    check_code="C.02",
                    severity="error",
                    message=(
                        f"Ссылка на таблицу {num} в абзаце «{_preview(text)}» "
                        f"не находит соответствующей таблицы"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        f"Проверить номер: таблицы {num} в документе нет. "
                        f"Возможно, опечатка в номере или забыли добавить таблицу."
                    ),
                    details={"paragraph_id": paragraph.id, "number": str(num)},
                )
            )

    return violations


# --- C.04 — ссылки [N] разрешаются в bibliography --------------------------


# Найти выражение вида «[1]», «[2, 3]», «[1-5]», «[1, 3-5, 7]».
# Содержимое скобок — одна или несколько групп: число или диапазон,
# разделённые запятыми. Между числами и разделителями допустимы пробелы.
_BIB_REF_RE = re.compile(r"\[(\d+(?:\s*[-–]\s*\d+|\s*,\s*\d+)*)\]")

# Внутри захваченной группы — отдельные «токены»: число или диапазон.
_BIB_TOKEN_RE = re.compile(r"\d+(?:\s*[-–]\s*\d+)?")
# Разбор одиночного токена на (start, end). Если это просто число — start == end.
_BIB_RANGE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
_BIB_SINGLE_RE = re.compile(r"(\d+)")


def _expand_bib_token(token: str) -> list[int]:
    """Развернуть токен «N» или «N-M» в список чисел [N..M]."""
    range_match = _BIB_RANGE_RE.fullmatch(token.strip())
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if end < start:
            return [start, end]
        return list(range(start, end + 1))
    single_match = _BIB_SINGLE_RE.fullmatch(token.strip())
    if single_match:
        return [int(single_match.group(1))]
    return []


@register("C.04")
def check_bibliography_references_resolve(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая ссылка `[N]` в тексте должна соответствовать существующей записи bibliography.

    Алгоритм:
    - Найти все вхождения вида `[N]`, `[N, M]`, `[N-M]` в тексте Paragraph'ов.
    - Разобрать содержимое скобок на отдельные номера (диапазоны
      разворачиваются: `[1-3]` → 1, 2, 3).
    - Каждый номер должен быть в диапазоне `1..len(document.bibliography)`.
    - Каждый «висячий» номер — отдельный Violation.

    Если bibliography пустой, а в тексте есть `[N]` — все номера нарушают
    (это явная ошибка, литературы в документе вообще нет).
    """
    _ = profile  # пока параметризации нет
    violations: list[Violation] = []
    bib_size = len(document.bibliography)

    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _BIB_REF_RE.finditer(text):
            inner = match.group(1)
            tokens = _BIB_TOKEN_RE.findall(inner)
            for token in tokens:
                numbers = _expand_bib_token(token)
                for num in numbers:
                    if 1 <= num <= bib_size:
                        continue
                    violations.append(
                        Violation(
                            check_code="C.04",
                            severity="error",
                            message=(
                                f"Ссылка [{num}] в абзаце «{_preview(text)}» "
                                f"не находит соответствующей записи в списке "
                                f"литературы"
                            ),
                            location=f"paragraph[{paragraph.id}]",
                            suggestion=(
                                f"В bibliography всего {bib_size} запис(ь/и/ей); "
                                f"проверьте номер ссылки [{num}]"
                            ),
                            details={
                                "paragraph_id": paragraph.id,
                                "number": str(num),
                                "bibliography_size": str(bib_size),
                            },
                        )
                    )

    return violations


# --- C.03 — ссылки на формулы разрешаются ---------------------------------


# Поиск ссылок на формулы в тексте:
# - «формула 1», «формуле 2», «формулу 3», «формулы 4» и пр.;
# - «(1)» — стандартный паттерн самой формулы (как Word её нумерует),
#   но и ссылка на формулу часто оформляется так же.
_FORMULA_REF_WORD_RE = re.compile(
    r"\bформул(?:а|е|у|ы|ой|ах|ам)?\s+\(?(\d+)\)?",
    re.IGNORECASE,
)
# Самостоятельная ссылка «(N)» — в скобках только число. Используем
# отрицательный look-behind по «формула»/«рис.»/«табл.», чтобы не
# дублировать матчи и не подхватить совсем посторонние числа в скобках.
_FORMULA_REF_PAREN_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])\((\d+)\)")


def _iter_formulas(items: Sequence[LogicalSection | Block]) -> list[Formula]:
    """Рекурсивно собрать все Formula (через LogicalSection.children)."""
    result: list[Formula] = []
    for item in items:
        if isinstance(item, Formula):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_formulas(item.children))
    return result


def _all_formulas(document: Document) -> list[Formula]:
    """Все Formula документа (плоско, со всех PageSection)."""
    formulas: list[Formula] = []
    for ps in document.page_sections:
        formulas.extend(_iter_formulas(ps.content))
    return formulas


def _formula_numbers(document: Document) -> set[int]:
    """Собрать множество номеров формул (только Formula с непустым number)."""
    return {f.number for f in _all_formulas(document) if f.number is not None}


@register("C.03")
def check_formula_references_resolve(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая ссылка на формулу N должна указывать на существующую формулу.

    Алгоритм:
    1. Собрать множество номеров формул из Formula.number (None — формула
       без номера, игнорируется).
    2. В каждом Paragraph искать паттерны:
       - «формула N», «формуле N», «формулу N», «формулы N» и пр.;
       - «(N)» — стандартный Word-паттерн самой формулы.
    3. Если N не входит в множество существующих — Violation.

    Если в документе вообще нет нумерованных формул, паттерн «(N)»
    не проверяется (это, скорее всего, какие-то иные числа в скобках).
    """
    _ = profile
    violations: list[Violation] = []
    existing = _formula_numbers(document)

    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        # Слово «формула N» — всегда проверяем (это явная ссылка).
        for match in _FORMULA_REF_WORD_RE.finditer(text):
            try:
                num = int(match.group(1))
            except ValueError:
                continue
            if num in existing:
                continue
            violations.append(
                Violation(
                    check_code="C.03",
                    severity="error",
                    message=(
                        f"Ссылка на формулу {num} в абзаце «{_preview(text)}» "
                        f"не находит соответствующей формулы"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        f"Проверить номер: формулы {num} в документе нет. "
                        f"Возможно, опечатка или формула не добавлена."
                    ),
                    details={"paragraph_id": paragraph.id, "number": str(num)},
                )
            )

        # Шаблон «(N)» — проверяем только если в документе вообще есть
        # нумерованные формулы (иначе слишком много ложных срабатываний).
        if not existing:
            continue
        for match in _FORMULA_REF_PAREN_RE.finditer(text):
            try:
                num = int(match.group(1))
            except ValueError:
                continue
            if num in existing:
                continue
            violations.append(
                Violation(
                    check_code="C.03",
                    severity="error",
                    message=(
                        f"Ссылка «({num})» в абзаце «{_preview(text)}» "
                        f"не находит соответствующей формулы"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        f"Проверить номер: формулы {num} в документе нет"
                    ),
                    details={"paragraph_id": paragraph.id, "number": str(num)},
                )
            )

    return violations


# --- C.05 — ссылки на приложения разрешаются ------------------------------


# Шаблон ссылки на приложение в тексте: «приложение X», «прил. X».
# X — одна РУССКАЯ ЗАГЛАВНАЯ буква.
_APPENDIX_REF_RE = re.compile(
    r"(?:приложени[еияй]|прил\.)\s+([А-Я])\b",
    re.IGNORECASE,
)
# Заголовок секции «Приложение X» — для построения множества существующих.
_APPENDIX_HEADING_RE = re.compile(r"^\s*Приложение\s+([А-Я])\b")


def _iter_logical_sections(
    items: Sequence[LogicalSection | Block],
) -> list[LogicalSection]:
    """Рекурсивно собрать все LogicalSection."""
    result: list[LogicalSection] = []
    for item in items:
        if isinstance(item, LogicalSection):
            result.append(item)
            result.extend(_iter_logical_sections(item.children))
    return result


def _existing_appendix_letters(document: Document) -> set[str]:
    """Множество букв приложений из заголовков LogicalSection."""
    letters: set[str] = set()
    for ps in document.page_sections:
        for section in _iter_logical_sections(ps.content):
            if section.level != 1:
                continue
            heading = "".join(
                el.text for el in section.heading if isinstance(el, TextRun)
            )
            match = _APPENDIX_HEADING_RE.match(heading)
            if match:
                letters.add(match.group(1).upper())
    return letters


@register("C.05")
def check_appendix_references_resolve(
    document: Document,
    profile: Profile,
) -> list[Violation]:
    """Каждая ссылка «приложение X» / «прил. X» должна указывать на существующее приложение.

    X — русская заглавная буква. Если в документе нет LogicalSection.level==1
    с заголовком «Приложение X» — Violation на ссылку.
    """
    _ = profile
    violations: list[Violation] = []
    existing = _existing_appendix_letters(document)

    for paragraph in _all_paragraphs(document):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        for match in _APPENDIX_REF_RE.finditer(text):
            letter = match.group(1).upper()
            if letter in existing:
                continue
            violations.append(
                Violation(
                    check_code="C.05",
                    severity="error",
                    message=(
                        f"Ссылка на приложение {letter} в абзаце "
                        f"«{_preview(text)}» не находит соответствующего "
                        f"приложения"
                    ),
                    location=f"paragraph[{paragraph.id}]",
                    suggestion=(
                        f"Проверить букву: приложения {letter} в документе нет. "
                        f"Возможно, опечатка или приложение не добавлено."
                    ),
                    details={"paragraph_id": paragraph.id, "letter": letter},
                )
            )

    return violations


__all__ = [
    "check_appendix_references_resolve",
    "check_bibliography_references_resolve",
    "check_figure_references_resolve",
    "check_formula_references_resolve",
    "check_table_references_resolve",
]
