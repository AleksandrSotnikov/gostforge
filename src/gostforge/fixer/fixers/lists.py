# ruff: noqa: RUF001, RUF002, RUF003

"""Фиксеры для категории L (списки)."""

from __future__ import annotations

from gostforge.model import (
    Block,
    Document,
    ListBlock,
    LogicalSection,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import FixApplied, register

# Знаки препинания, которые могут быть в конце элемента списка.
# Удаляются при нормализации.
_TRAILING_PUNCTUATION = {".", ",", ";", ":", "!", "?"}


def _iter_lists(items: list[LogicalSection | Block]) -> list[ListBlock]:
    """Рекурсивно собрать все ListBlock из дерева содержимого."""
    out: list[ListBlock] = []
    for item in items:
        if isinstance(item, ListBlock):
            out.append(item)
        elif isinstance(item, LogicalSection):
            out.extend(_iter_lists(item.children))
    return out


def _all_lists(document: Document) -> list[ListBlock]:
    lists: list[ListBlock] = []
    for ps in document.page_sections:
        lists.extend(_iter_lists(ps.content))
    return lists


def _last_text_run(item: list) -> TextRun | None:  # type: ignore[no-untyped-def]
    """Найти последний TextRun в элементе списка (с непустым text)."""
    for el in reversed(item):
        if isinstance(el, TextRun) and el.text:
            return el
    return None


def _strip_trailing_punct(text: str) -> str:
    """Убрать ВСЕ хвостовые знаки препинания и пробелы."""
    while text and (text[-1] in _TRAILING_PUNCTUATION or text[-1].isspace()):
        text = text[:-1]
    return text


@register("L.04")
def fix_list_item_punctuation(
    document: Document,
    profile: Profile,
) -> list[FixApplied]:
    """Привести пунктуацию в концах элементов списка к ГОСТу.

    По ГОСТ 7.32-2017 п. 6.5.1: после каждого пункта перечисления —
    «;», после последнего — «.». Этот фиксер:

    1. Берёт каждый ListBlock документа.
    2. Удаляет все хвостовые знаки и пробелы у каждого item.
    3. Добавляет «;» после всех пунктов кроме последнего, «.» — после
       последнего.

    Параметры профиля ``checks.L.04.params``:
    * ``trailing_intermediate`` (default ";")  — знак после промежуточных;
    * ``trailing_last`` (default ".") — знак после последнего;
    * ``enabled_for_ordered`` (default True) — применять и к нумерованным.

    Чтобы выключить только нумерованные списки (где иногда пунктуация
    не нужна, например в `1) шаг 1` без знаков) — установите
    ``enabled_for_ordered=False``.
    """
    config = profile.checks.get("L.04")
    inter = ";"
    last = "."
    apply_ordered = True
    if config:
        if config.params.get("trailing_intermediate"):
            inter = str(config.params["trailing_intermediate"])
        if config.params.get("trailing_last"):
            last = str(config.params["trailing_last"])
        if config.params.get("enabled_for_ordered") is not None:
            apply_ordered = bool(config.params["enabled_for_ordered"])

    applied: list[FixApplied] = []
    for lst in _all_lists(document):
        if lst.ordered and not apply_ordered:
            continue
        n = len(lst.items)
        if n == 0:
            continue
        for idx, item in enumerate(lst.items):
            run = _last_text_run(item)
            if run is None:
                continue
            old_text = run.text
            cleaned = _strip_trailing_punct(old_text)
            # Если элемент пустой после очистки — оставляем как есть.
            if not cleaned.strip():
                continue
            suffix = last if idx == n - 1 else inter
            new_text = cleaned + suffix
            if new_text == old_text:
                continue
            run.text = new_text
            applied.append(
                FixApplied(
                    fixer_code="L.04",
                    location=f"list[{lst.id}].item[{idx}]",
                    description=(
                        f"Пунктуация: «{old_text[-3:]!r}» → «{suffix}»"
                    ),
                )
            )
    return applied


__all__ = ["fix_list_item_punctuation"]
