"""Фиксеры для категории F (страница, поля, нумерация)."""

from __future__ import annotations

from typing import Literal, cast

from gostforge.model import (
    ContentTemplate,
    Document,
    HeaderConfig,
    InlineElement,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import FixApplied, register

# Допуск полей (мм) — как в проверке F.01.
_MARGIN_TOLERANCE_MM = 0.5


@register("F.01")
def fix_margins(document: Document, profile: Profile) -> list[FixApplied]:
    """Привести поля страницы к профилю.

    Эталонные поля — ``profile.styles.page.margins_mm`` (по умолчанию для
    ГОСТ 7.32: 20/15/20/30 мм). Меняем только те стороны, что отклоняются
    больше допуска (0.5 мм) — как и проверка F.01.
    """
    expected = profile.styles.page.margins_mm
    applied: list[FixApplied] = []
    for section in document.page_sections:
        actual = section.page.margins_mm
        changed_sides: list[str] = []
        for side in ("top", "right", "bottom", "left"):
            exp = expected.get(side)
            act = actual.get(side)
            if exp is None or act is None:
                continue
            if abs(exp - act) > _MARGIN_TOLERANCE_MM:
                actual[side] = exp
                changed_sides.append(f"{side}={exp}")
        if changed_sides:
            applied.append(
                FixApplied(
                    fixer_code="F.01",
                    location=f"page_sections.{section.id}.page.margins_mm",
                    description="Поля приведены к профилю: " + ", ".join(changed_sides),
                )
            )
    return applied


@register("F.02")
def fix_paper_size(document: Document, profile: Profile) -> list[FixApplied]:
    """Привести формат бумаги к профилю (по умолчанию A4).

    Параметр ``checks.F.02.params.paper`` перекрывает
    ``profile.styles.page.size``.
    """
    config = profile.checks.get("F.02")
    expected = profile.styles.page.size or "A4"
    if config and config.params.get("paper"):
        expected = str(config.params["paper"])

    applied: list[FixApplied] = []
    for section in document.page_sections:
        old = section.page.paper
        if old == expected:
            continue
        section.page.paper = expected
        applied.append(
            FixApplied(
                fixer_code="F.02",
                location=f"page_sections.{section.id}.page.paper",
                description=f"Формат бумаги «{old}» → «{expected}»",
            )
        )
    return applied


@register("F.03")
def fix_orientation(document: Document, profile: Profile) -> list[FixApplied]:
    """Привести ориентацию страницы к профилю (по умолчанию portrait).

    Секции типа ``appendix`` пропускаем — у приложений по ГОСТ допустима
    альбомная ориентация (как и в проверке F.03).
    """
    config = profile.checks.get("F.03")
    expected = "portrait"
    if config and config.params.get("orientation"):
        expected = str(config.params["orientation"])
    if expected not in {"portrait", "landscape"}:
        return []

    applied: list[FixApplied] = []
    for section in document.page_sections:
        if section.type == "appendix":
            continue
        old = section.page.orientation
        if old == expected:
            continue
        section.page.orientation = cast(Literal["portrait", "landscape"], expected)
        applied.append(
            FixApplied(
                fixer_code="F.03",
                location=f"page_sections.{section.id}.page.orientation",
                description=f"Ориентация «{old}» → «{expected}»",
            )
        )
    return applied


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


@register("F.05")
def fix_page_number_format(
    document: Document,
    profile: Profile,
) -> list[FixApplied]:
    """Привести формат нумерации страниц к профилю (по умолчанию arabic).

    Зеркально проверке F.05: применяется только к ``PageSection``, где
    ``page_numbering.visible``. Параметр ``checks.F.05.params.format``
    перекрывает ожидание (``arabic`` | ``roman`` | ``uppercase_letter``).
    Безопасная правка: меняется только стиль глифа номера, не сам текст.
    """
    config = profile.checks.get("F.05")
    expected = "arabic"
    if config and config.params.get("format"):
        expected = str(config.params["format"])
    if expected not in {"arabic", "roman", "uppercase_letter"}:
        return []

    applied: list[FixApplied] = []
    for section in document.page_sections:
        numbering = section.page_numbering
        if not numbering.visible:
            continue
        old = numbering.format
        if old == expected:
            continue
        numbering.format = cast(
            Literal["arabic", "roman", "uppercase_letter"],
            expected,
        )
        applied.append(
            FixApplied(
                fixer_code="F.05",
                location=f"page_sections.{section.id}.page_numbering.format",
                description=f"Формат нумерации страниц «{old}» → «{expected}»",
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


__all__ = [
    "fix_margins",
    "fix_orientation",
    "fix_page_number_format",
    "fix_page_number_position",
    "fix_page_numbering_start",
    "fix_paper_size",
]
