"""L.* — проверки списков (маркеры, нумерация, пунктуация)."""

from __future__ import annotations

import re
from collections.abc import Sequence

from gostforge.model import (
    Block,
    Document,
    InlineElement,
    ListBlock,
    LogicalSection,
    PageSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register

# Маркеры ненумерованного списка по умолчанию (если не задано в профиле).
_DEFAULT_ALLOWED_MARKERS: list[str] = ["•", "-", "–"]

# Набор «известных» маркеров: символ в начале первого пункта, если он
# принадлежит этому множеству, считается «реальным» маркером (заданным
# в тексте, а не Word-стилем). Остальные стартовые символы трактуются
# как «маркер задан стилем» и проверка не срабатывает.
_KNOWN_BULLET_MARKERS: frozenset[str] = frozenset(
    {"•", "-", "–", "—", "*", "·", "◦", "○", "▪", "■", "►", "→"}
)


def _iter_list_blocks(items: Sequence[LogicalSection | Block]) -> list[ListBlock]:
    """Рекурсивно собрать все ListBlock из content (через LogicalSection.children)."""
    result: list[ListBlock] = []
    for item in items:
        if isinstance(item, ListBlock):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_list_blocks(item.children))
    return result


def _all_list_blocks(document: Document) -> list[tuple[PageSection, ListBlock]]:
    """Все ListBlock документа — со ссылкой на PageSection (для location)."""
    result: list[tuple[PageSection, ListBlock]] = []
    for ps in document.page_sections:
        for lb in _iter_list_blocks(ps.content):
            result.append((ps, lb))
    return result


def _item_text(item: Sequence[InlineElement]) -> str:
    """Склеить текст одного пункта списка из TextRun-ов."""
    return "".join(el.text for el in item if isinstance(el, TextRun))


@register("L.01")
def check_unordered_list_marker(document: Document, profile: Profile) -> list[Violation]:
    """Маркер ненумерованного списка должен быть из списка разрешённых.

    Параметры `checks.L.01.params`:
    - `allowed_markers` (list[str]): разрешённые маркеры, по умолчанию
      `["•", "-", "–"]`.

    Эвристика Фазы 1: парсер не знает реального маркера из docx, поэтому
    смотрим на первый непробельный символ текста items[0]. Если этот
    символ принадлежит набору «известных маркеров» и его нет в
    `allowed_markers` — нарушение. Если первый символ — буква/цифра
    (значит маркер задан Word-стилем) — пропускаем.
    """
    violations: list[Violation] = []
    config = profile.checks.get("L.01")
    allowed: list[str] = list(_DEFAULT_ALLOWED_MARKERS)
    if config and config.params.get("allowed_markers") is not None:
        param = config.params["allowed_markers"]
        if isinstance(param, list) and param:
            allowed = [str(m) for m in param]

    allowed_set = set(allowed)

    for page_section, lb in _all_list_blocks(document):
        if lb.ordered:
            continue
        if not lb.items:
            continue
        first_text = _item_text(lb.items[0]).lstrip()
        if not first_text:
            continue
        marker = first_text[0]
        if marker not in _KNOWN_BULLET_MARKERS:
            # Не похоже на текстовый маркер — значит, задан стилем Word.
            continue
        if marker in allowed_set:
            continue
        violations.append(
            Violation(
                check_code="L.01",
                severity="warning",
                message=(
                    f"Маркер «{marker}» в ненумерованном списке «{lb.id}» "
                    f"не входит в список разрешённых: "
                    f"{', '.join(allowed)}"
                ),
                location=f"page_sections.{page_section.id}.list[{lb.id}]",
                suggestion=("Использовать один из разрешённых маркеров: " + ", ".join(allowed)),
                details={
                    "list_id": lb.id,
                    "marker": marker,
                    "allowed": ", ".join(allowed),
                },
            )
        )
    return violations


# L.02: распознать формат нумерации первого пункта.
# - «1)»  — цифра, закрывающая круглая скобка
# - «1.»  — цифра и точка
# - «1»   — цифра без префикса (значит формат задан стилем)
# Если префикс не распознан вовсе — формат «unknown» (формат скрыт стилем).
_NUM_FORMAT_PAREN = re.compile(r"^\s*\d+\s*\)\s*")
_NUM_FORMAT_DOT = re.compile(r"^\s*\d+\s*\.\s*")
_NUM_FORMAT_BARE = re.compile(r"^\s*\d+\s+")


def _ordered_item_format(item: Sequence[InlineElement]) -> str | None:
    """Определить формат нумерации первого пункта.

    Возвращает одно из: 'paren' (1)), 'dot' (1.), 'bare' (1 ),
    либо None — если префикс не распознан (формат скрыт Word-стилем).
    """
    text = _item_text(item)
    if not text:
        return None
    # Порядок важен: «1)» и «1.» должны распознаваться раньше «1 ».
    if _NUM_FORMAT_PAREN.match(text):
        return "paren"
    if _NUM_FORMAT_DOT.match(text):
        return "dot"
    if _NUM_FORMAT_BARE.match(text):
        return "bare"
    return None


@register("L.02")
def check_ordered_list_uniform_format(document: Document, profile: Profile) -> list[Violation]:
    """Стиль нумерации нумерованных списков должен быть единообразным.

    Эвристика Фазы 1: для каждого ListBlock с ordered=True смотрим формат
    первого пункта — «1)», «1.», «1 » (см. _ordered_item_format). Если в
    документе встречаются разные форматы — Violation на каждый «отклоняющийся»
    список. Списки, где формат не распознан (None — задан стилем Word),
    в сравнении не участвуют.
    """
    violations: list[Violation] = []
    ordered_lists = [(ps, lb) for ps, lb in _all_list_blocks(document) if lb.ordered and lb.items]
    if len(ordered_lists) < 2:
        return violations

    formats: list[tuple[PageSection, ListBlock, str]] = []
    for ps, lb in ordered_lists:
        fmt = _ordered_item_format(lb.items[0])
        if fmt is None:
            continue
        formats.append((ps, lb, fmt))

    distinct = {fmt for _ps, _lb, fmt in formats}
    if len(distinct) <= 1:
        return violations

    # Берём «эталонный» формат как самый часто встречающийся, остальные
    # помечаем как нарушения. При равенстве — стабильно первый по порядку.
    counts: dict[str, int] = {}
    for _ps, _lb, fmt in formats:
        counts[fmt] = counts.get(fmt, 0) + 1
    expected = max(counts, key=lambda f: (counts[f], -list(counts).index(f)))

    for ps, lb, fmt in formats:
        if fmt == expected:
            continue
        violations.append(
            Violation(
                check_code="L.02",
                severity="warning",
                message=(
                    f"Формат нумерации «{fmt}» в списке «{lb.id}» отличается "
                    f"от преобладающего «{expected}»"
                ),
                location=f"page_sections.{ps.id}.list[{lb.id}]",
                suggestion=(
                    "Привести нумерацию всех списков документа к одному "
                    f"формату (например, «{expected}»)"
                ),
                details={
                    "list_id": lb.id,
                    "format": fmt,
                    "expected": expected,
                },
            )
        )
    return violations


# L.04: множество знаков, по которым мы оцениваем «концовку» пункта.
# Любой иной символ (буква/цифра/закрывающая кавычка) трактуется как
# «без знака» (категория " ").
_END_PUNCTUATION_MARKS: frozenset[str] = frozenset({".", ";", "?", "!"})


def _item_end_marker(item: Sequence[InlineElement]) -> str:
    """Определить «концовку» пункта списка.

    Возвращает один из символов из `_END_PUNCTUATION_MARKS` (если пункт
    оканчивается на этот символ), либо `" "` для случая «без знака» /
    пустой пункт. Используется L.04 для сравнения концовок пунктов внутри
    одного списка.
    """
    text = _item_text(item).rstrip()
    if not text:
        return " "
    last_char = text[-1]
    if last_char in _END_PUNCTUATION_MARKS:
        return last_char
    return " "


@register("L.04")
def check_list_item_punctuation_uniform(document: Document, profile: Profile) -> list[Violation]:
    """Знаки препинания в конце пунктов списка должны быть единообразны.

    В каждом ListBlock все items[i] должны заканчиваться одинаково:
    либо все `;`, либо все `.`, либо все без знака. Любой `?`, `!` также
    учитывается. Если в одном списке встречаются разные концовки — Violation
    (severity=info).
    """
    violations: list[Violation] = []
    for page_section, lb in _all_list_blocks(document):
        if len(lb.items) < 2:
            continue
        markers = [_item_end_marker(item) for item in lb.items]
        distinct = set(markers)
        if len(distinct) <= 1:
            continue
        # Превратим " " в человекочитаемое «без знака» только для сообщения.
        readable = sorted({m if m != " " else "(без знака)" for m in distinct})
        violations.append(
            Violation(
                check_code="L.04",
                severity="info",
                message=(
                    f"В списке «{lb.id}» пункты оканчиваются по-разному: {', '.join(readable)}"
                ),
                location=f"page_sections.{page_section.id}.list[{lb.id}]",
                suggestion=(
                    "Привести все пункты к единому стилю окончания: "
                    "все с «;», все с «.» или все без знака"
                ),
                details={
                    "list_id": lb.id,
                    "markers": ",".join(sorted(distinct)),
                },
            )
        )
    return violations


@register("L.03")
def check_list_item_indent_uniform(document: Document, profile: Profile) -> list[Violation]:
    """Отступы пунктов списка должны быть одинаковыми.

    На Фазе 1 модель не хранит отступы для items внутри ListBlock —
    `ListBlock.items: list[list[InlineElement]]` без сопровождающих
    параграфных свойств. Проверка зарегистрирована, чтобы сохранить код
    в реестре и YAML-профиле; реальная логика появится на Фазе 2,
    когда в модели будет per-item indent.

    # TODO Phase 2: добавить indent в ListBlock-items model
    """
    # На Фазе 1 нет данных для оценки — возвращаем пустой список.
    _ = (document, profile)  # явный no-op, чтобы не было unused-warning
    return []


__all__ = [
    "check_list_item_indent_uniform",
    "check_list_item_punctuation_uniform",
    "check_ordered_list_uniform_format",
    "check_unordered_list_marker",
]
