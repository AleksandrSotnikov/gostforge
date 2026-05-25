# ruff: noqa: RUF001, RUF002, RUF003

"""L.* — проверки списков (маркеры, нумерация, пунктуация)."""

from __future__ import annotations

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
def check_unordered_list_marker(
    document: Document, profile: Profile
) -> list[Violation]:
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
                suggestion=(
                    "Использовать один из разрешённых маркеров: "
                    + ", ".join(allowed)
                ),
                details={
                    "list_id": lb.id,
                    "marker": marker,
                    "allowed": ", ".join(allowed),
                },
            )
        )
    return violations


__all__ = [
    "check_unordered_list_marker",
]
