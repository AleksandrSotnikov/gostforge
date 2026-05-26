"""Фиксеры для категории F (страница, поля, нумерация)."""

from __future__ import annotations

from gostforge.model import (
    ContentTemplate,
    Document,
    HeaderConfig,
    InlineElement,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import FixApplied, register


@register("F.06")
def fix_page_numbering_start(
    document: Document,
    profile: Profile,
) -> list[FixApplied]:
    """Установить `start_value` нумерации страниц согласно профилю.

    Параметр профиля ``checks.F.06.params.start_value`` (например, 3 —
    нумерация продолжается с титула, но видна только с третьей страницы).

    Применяется только к ``PageSection``, где ``page_numbering.visible``
    и ``start_mode == 'start_at'``. Continue-секции не трогаем.
    """
    config = profile.checks.get("F.06")
    expected_raw = config.params.get("start_value") if config else None
    if expected_raw is None:
        return []
    try:
        expected = int(expected_raw)
    except (TypeError, ValueError):
        return []

    applied: list[FixApplied] = []
    for section in document.page_sections:
        numbering = section.page_numbering
        if not numbering.visible:
            continue
        if numbering.start_mode != "start_at":
            continue
        old = numbering.start_value
        if old == expected:
            continue
        numbering.start_value = expected
        applied.append(
            FixApplied(
                fixer_code="F.06",
                location=f"page_sections.{section.id}.page_numbering.start_value",
                description=f"start_value {old} → {expected}",
            )
        )
    return applied


@register("F.04")
def fix_page_number_position(
    document: Document,
    profile: Profile,
) -> list[FixApplied]:
    """Установить позицию номера страницы согласно профилю.

    Параметр ``checks.F.04.params.position``: 'bottom_center' (default),
    'bottom_right', 'bottom_left', 'top_center', 'top_right', 'top_left'.

    Если в нужном слоте уже есть `{page}` — no-op. Иначе помещаем
    туда `[TextRun("{page}")]`.

    Применяется только к секциям с ``page_numbering.visible``.
    """
    config = profile.checks.get("F.04")
    position = "bottom_center"
    if config and config.params.get("position"):
        position = str(config.params["position"])
    try:
        vertical, slot = position.split("_", 1)
    except ValueError:
        return []
    if vertical not in {"top", "bottom"} or slot not in {"left", "center", "right"}:
        return []

    applied: list[FixApplied] = []
    for section in document.page_sections:
        if not section.page_numbering.visible:
            continue
        target_attr = "footer" if vertical == "bottom" else "header"
        target = getattr(section, target_attr)
        if target is None:
            # Создаём HeaderConfig с пустым default-шаблоном.
            target = HeaderConfig(default=ContentTemplate())
            setattr(section, target_attr, target)
        template = target.default
        # Проверим, есть ли уже {page} в нужном слоте — no-op.
        current_slot = getattr(template, slot)
        if _has_page_placeholder(current_slot):
            continue
        # Удалим {page} из других слотов (чтобы не было дублей).
        moved_from = None
        for s in ("left", "center", "right"):
            existing = getattr(template, s)
            if _has_page_placeholder(existing):
                setattr(template, s, _strip_page_placeholder(existing))
                moved_from = s
        # Поместим в нужный слот.
        setattr(template, slot, [TextRun(text="{page}")])
        applied.append(
            FixApplied(
                fixer_code="F.04",
                location=f"page_sections.{section.id}.{target_attr}.default.{slot}",
                description=(
                    f"Перемещено {{page}} в {slot}"
                    + (f" (был в {moved_from})" if moved_from else "")
                ),
            )
        )
    return applied


def _has_page_placeholder(content) -> bool:  # type: ignore[no-untyped-def]
    """True, если в content есть TextRun с text == '{page}'."""
    if not content:
        return False
    return any(isinstance(el, TextRun) and el.text == "{page}" for el in content)


def _strip_page_placeholder(
    content: list[InlineElement] | None,
) -> list[InlineElement]:
    """Убрать все {page}-плейсхолдеры из content."""
    return [el for el in (content or []) if not (isinstance(el, TextRun) and el.text == "{page}")]


__all__ = ["fix_page_number_position", "fix_page_numbering_start"]
