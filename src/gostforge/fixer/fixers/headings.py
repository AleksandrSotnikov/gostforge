"""H.* — фиксеры заголовков логических разделов."""

from __future__ import annotations

import re

from gostforge.model import (
    Block,
    Document,
    LogicalSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import FixApplied, register

# Шаблон «номер заголовка с точкой»: «1. Введение», «1.2. Анализ».
# Группы: 1 — номер, 2 — точка, 3 — следующий пробельный символ.
_NUMBER_WITH_DOT = re.compile(r"^(\d+(?:\.\d+)*)(\.)(\s)")

# Ведущая нумерация заголовка, которую нужно срезать перед авто-простановкой:
# - чистый номер: «1 », «1. », «1.2 », «1.2.1. »;
# - со словесной меткой раздела: «ГЛАВА 1. », «Глава 2 », «Раздел 3. ».
# Без метки ГОСТ 7.32 нумерует разделы просто числом, поэтому «ГЛАВА N»
# воспринимаем как уже-нумерацию и заменяем её на канонический номер.
_LEADING_NUMBER_RE = re.compile(
    r"^(?:(?:глава|раздел|часть)\s+)?\d+(?:\.\d+)*\.?\s+",
    re.IGNORECASE,
)


def _iter_logical_sections(
    items: list[LogicalSection | Block],
) -> list[LogicalSection]:
    """Рекурсивно собрать все LogicalSection документа."""
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


def _heading_runs(section: LogicalSection) -> list[TextRun]:
    """TextRun-ы из heading логического раздела."""
    return [el for el in section.heading if isinstance(el, TextRun)]


def _heading_location(section: LogicalSection) -> str:
    """Стандартный путь в модели для FixApplied.location."""
    return f"page_sections.*.logical_section[{section.id}].heading"


@register("H.03")
def fix_dot_after_heading_number(document: Document, profile: Profile) -> list[FixApplied]:
    """Убрать точку после номера в заголовке.

    Заменяет «1. Введение» → «1 Введение», «1.2. Анализ» → «1.2 Анализ».
    Точка убирается только сразу после номера, точки в любом другом месте
    заголовка сохраняются. Номер всегда находится в начале первого
    TextRun-а — там и применяется замена.
    """
    applied: list[FixApplied] = []
    for section in _all_logical_sections(document):
        runs = _heading_runs(section)
        if not runs:
            continue
        first = runs[0]
        if not first.text:
            continue
        match = _NUMBER_WITH_DOT.match(first.text)
        if not match:
            continue
        number = match.group(1)
        whitespace = match.group(3)
        new_prefix = f"{number}{whitespace}"
        new_text = new_prefix + first.text[match.end() :]
        first.text = new_text
        applied.append(
            FixApplied(
                fixer_code="H.03",
                location=_heading_location(section),
                description="Убрана точка после номера заголовка",
                details={"number": number},
            )
        )
    return applied


@register("H.08")
def fix_heading_trailing_dot(document: Document, profile: Profile) -> list[FixApplied]:
    """Убрать точку (или многоточие) в конце заголовка.

    Не трогает `?` и `:` — они по ГОСТ допустимы. Работает с последним
    непустым TextRun-ом заголовка: отрезает завершающие `...`, `…` или
    одиночную `.`. Хвостовые пробелы предварительно учитываются.
    """
    applied: list[FixApplied] = []
    for section in _all_logical_sections(document):
        runs = _heading_runs(section)
        last_run: TextRun | None = None
        for run in runs:
            if run.text:
                last_run = run
        if last_run is None:
            continue

        original = last_run.text
        # Учитываем хвостовые пробелы при определении окончания, но при
        # записи сохраняем их (rstrip-ом займётся T.09, не наш фиксер).
        stripped = original.rstrip()
        if not stripped:
            continue
        trailing_ws = original[len(stripped) :]

        if stripped.endswith("..."):
            new_stripped = stripped[:-3]
            suffix = "..."
        elif stripped.endswith("…"):
            new_stripped = stripped[:-1]
            suffix = "…"
        elif stripped.endswith("."):
            new_stripped = stripped[:-1]
            suffix = "."
        else:
            continue

        last_run.text = new_stripped + trailing_ws
        applied.append(
            FixApplied(
                fixer_code="H.08",
                location=_heading_location(section),
                description="Убрана точка в конце заголовка",
                details={"removed": suffix},
            )
        )
    return applied


@register("H.04")
def fix_heading_auto_numbering(
    document: Document,
    profile: Profile,
) -> list[FixApplied]:
    """Авто-нумерация содержательных разделов: '1', '1.1', '1.1.1'.

    По ГОСТ 7.32-2017 п. 6.2: разделы и подразделы основной части
    нумеруются арабскими цифрами. Структурные разделы (Введение,
    Заключение, Содержание, Реферат, Список источников, Приложения)
    не нумеруются.

    Алгоритм симметричен UI-кнопке «Авто-нумерация» в bulk-операциях
    Streamlit-конструктора, но реализован на уровне модели Document
    через рекурсивный обход иерархии секций.

    Не активен по умолчанию (`profile.checks.H.04.enabled` контролирует).
    """
    config = profile.checks.get("H.04")
    if not (config and config.enabled):
        return []

    applied: list[FixApplied] = []
    top_idx = 0
    for ps in document.page_sections:
        for sec in ps.content:
            if not isinstance(sec, LogicalSection):
                continue
            heading_text = _heading_text(sec)
            if _is_structural_heading(heading_text):
                # Нормализуем — убираем случайную нумерацию.
                _set_heading_text(sec, _strip_existing_number(heading_text))
                # Подразделы внутри Содержание/Введение и т. п. тоже не нумеруются.
                continue
            top_idx += 1
            base = _strip_existing_number(heading_text)
            new_text = f"{top_idx} {base}"
            if new_text != heading_text:
                _set_heading_text(sec, new_text)
                applied.append(
                    FixApplied(
                        fixer_code="H.04",
                        location=_heading_location(sec),
                        description=f"«{heading_text}» → «{new_text}»",
                    )
                )
            # Рекурсивно нумеруем подразделы.
            _renumber_subsections(sec, prefix=str(top_idx), applied=applied)
    return applied


def _renumber_subsections(
    parent: LogicalSection,
    *,
    prefix: str,
    applied: list[FixApplied],
) -> None:
    """Простановка номеров 'prefix.K' для подразделов parent и
    'prefix.K.M' для их подподразделов."""
    sub_idx = 0
    for child in parent.children:
        if not isinstance(child, LogicalSection):
            continue
        old_text = _heading_text(child)
        if _is_structural_heading(old_text):
            _set_heading_text(child, _strip_existing_number(old_text))
            continue
        sub_idx += 1
        base = _strip_existing_number(old_text)
        new_text = f"{prefix}.{sub_idx} {base}"
        if new_text != old_text:
            _set_heading_text(child, new_text)
            applied.append(
                FixApplied(
                    fixer_code="H.04",
                    location=_heading_location(child),
                    description=f"«{old_text}» → «{new_text}»",
                )
            )
        _renumber_subsections(child, prefix=f"{prefix}.{sub_idx}", applied=applied)


def _heading_text(section: LogicalSection) -> str:
    """Склейка inline-элементов заголовка в строку."""
    return "".join(el.text for el in section.heading if isinstance(el, TextRun))


def _set_heading_text(section: LogicalSection, text: str) -> None:
    """Заменить весь heading на один TextRun(text=...).

    Существующее форматирование heading-runs теряется — это OK
    для авто-нумерации (Heading-стиль применяется к всему параграфу
    в экспортёре).
    """
    section.heading = [TextRun(text=text)]


# Структурные разделы (Введение, Заключение, Приложение, ...) — не нумеруются.
_STRUCTURAL = frozenset(
    {
        "введение",
        "заключение",
        "содержание",
        "реферат",
        "список использованных источников",
        "список литературы",
        "литература",
        "список источников",
        "библиографический список",
        "оглавление",
        "перечень сокращений",
        "перечень обозначений и сокращений",
    }
)


def _is_structural_heading(heading: str) -> bool:
    cleaned = _strip_existing_number(heading).strip().lower()
    if cleaned in _STRUCTURAL:
        return True
    return bool(cleaned.startswith("приложение"))


def _strip_existing_number(heading: str) -> str:
    """Убрать существующую нумерацию с начала заголовка.

    Распознаёт как чистый номер («1», «1.», «1.1»), так и словесную метку
    раздела с номером («ГЛАВА 1.», «Раздел 2») — чтобы авто-нумерация не
    давала «1 ГЛАВА 1. …».
    """
    return _LEADING_NUMBER_RE.sub("", heading).strip()


__all__ = [
    "fix_dot_after_heading_number",
    "fix_heading_auto_numbering",
    "fix_heading_trailing_dot",
]
