"""K.* — фиксеры колонтитулов и нумерации на уровне PageSection-ов.

Симметричны проверкам ``validator/checks/page_sections.py``. Правят
только метаданные нумерации секций (``page_numbering``) — это безопасные
правки вёрстки, не затрагивающие текст:

* K.02 — отключить номер на титульном листе.
* K.03 — задать стартовую страницу основной части (start_at + value).
* K.04 — убрать сбросы сквозной нумерации (restart → continue).
"""

from __future__ import annotations

from gostforge.model import Document
from gostforge.profile import Profile

from ..engine import FixApplied, register


@register("K.02")
def fix_title_page_number(document: Document, profile: Profile) -> list[FixApplied]:
    """Отключить отображение номера страницы на титульном листе (K.02).

    ГОСТ 7.32-2017 п. 6.1.1: на титульном листе номер не печатается
    (страница учитывается при сквозной нумерации). Зеркально проверке
    K.02: для каждой секции ``type == "title"`` с ``visible == True``
    выставляем ``visible = False``.
    """
    _ = profile
    applied: list[FixApplied] = []
    for section in document.page_sections:
        if section.type != "title":
            continue
        if not section.page_numbering.visible:
            continue
        section.page_numbering.visible = False
        applied.append(
            FixApplied(
                fixer_code="K.02",
                location=f"page_sections.{section.id}.page_numbering.visible",
                description="Отключён номер страницы на титульном листе",
            )
        )
    return applied


@register("K.03")
def fix_main_section_start_value(document: Document, profile: Profile) -> list[FixApplied]:
    """Задать стартовую страницу нумерации основной части (K.03).

    Зеркально проверке K.03: у первой секции типа "main" (а если её нет —
    первой не-title секции) выставляем ``start_mode = "start_at"`` и
    ``start_value = expected_start_value`` (по умолчанию 3).
    """
    from gostforge.validator.checks.page_sections import _first_main_section

    config = profile.checks.get("K.03")
    expected_start = 3
    if config is not None:
        raw = config.params.get("expected_start_value", 3)
        try:
            expected_start = int(raw)
        except (TypeError, ValueError):
            expected_start = 3

    section = _first_main_section(document)
    if section is None:
        return []

    numbering = section.page_numbering
    applied: list[FixApplied] = []
    if numbering.start_mode != "start_at":
        old_mode = numbering.start_mode
        numbering.start_mode = "start_at"
        numbering.start_value = expected_start
        applied.append(
            FixApplied(
                fixer_code="K.03",
                location=f"page_sections.{section.id}.page_numbering.start_mode",
                description=(
                    f"Нумерация основной части: start_mode «{old_mode}» → «start_at», "
                    f"start_value → {expected_start}"
                ),
            )
        )
    elif numbering.start_value != expected_start:
        old_value = numbering.start_value
        numbering.start_value = expected_start
        applied.append(
            FixApplied(
                fixer_code="K.03",
                location=f"page_sections.{section.id}.page_numbering.start_value",
                description=f"start_value основной части {old_value} → {expected_start}",
            )
        )
    return applied


@register("K.04")
def fix_no_numbering_restarts(document: Document, profile: Profile) -> list[FixApplied]:
    """Убрать сбросы сквозной нумерации (K.04).

    Зеркально проверке K.04: всем секциям, кроме первой, с
    ``start_mode == "restart"`` выставляем ``start_mode = "continue"``.
    Параметр ``allow_restart_in_appendix`` (default False) сохраняет
    рестарт в приложениях, если он разрешён профилем.
    """
    config = profile.checks.get("K.04")
    allow_restart_in_appendix = False
    if config is not None:
        allow_restart_in_appendix = bool(config.params.get("allow_restart_in_appendix", False))

    applied: list[FixApplied] = []
    for index, section in enumerate(document.page_sections):
        if index == 0:
            continue  # первая секция задаёт начало нумерации
        if section.page_numbering.start_mode != "restart":
            continue
        if allow_restart_in_appendix and section.type == "appendix":
            continue
        section.page_numbering.start_mode = "continue"
        applied.append(
            FixApplied(
                fixer_code="K.04",
                location=f"page_sections.{section.id}.page_numbering.start_mode",
                description="Сброс нумерации убран: start_mode «restart» → «continue»",
            )
        )
    return applied


__all__ = [
    "fix_main_section_start_value",
    "fix_no_numbering_restarts",
    "fix_title_page_number",
]
