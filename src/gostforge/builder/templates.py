"""Готовые шаблоны-скелеты для типовых видов работ.

Каждый шаблон создаёт `WorkBuilder` с уже добавленными обязательными
разделами (с плейсхолдер-подсказками вместо «лорем ипсума»). Это даёт
студенту валидный по структуре каркас, который сразу проходит S.01.
"""

from __future__ import annotations

from .work_builder import WorkBuilder, work

# Унифицированный плейсхолдер для пустых разделов: студент заменяет его
# реальным текстом. Намеренно не «Lorem ipsum» — чтобы видно было, что
# раздел требует заполнения.
_PLACEHOLDER = "<Заполните этот раздел>"


def coursework_template(
    title: str,
    author: str,
    supervisor: str = "",
    organization: str = "",
    year: int | None = None,
) -> WorkBuilder:
    """Скелет курсовой: введение, основная часть, заключение, список источников."""
    builder = work(
        title=title,
        author=author,
        year=year,
        work_type="coursework",
        supervisor=supervisor,
        organization=organization,
    )
    (
        builder.section("Введение")
        .paragraph(_PLACEHOLDER)
        .section("Глава 1. Основная часть")
        .paragraph(_PLACEHOLDER)
        .section("Заключение")
        .paragraph(_PLACEHOLDER)
        .section("Список использованных источников")
    )
    return builder


def bachelor_thesis_template(
    title: str,
    author: str,
    supervisor: str = "",
    organization: str = "",
    year: int | None = None,
) -> WorkBuilder:
    """Скелет бакалаврской ВКР: реферат, введение, две главы, заключение, список."""
    builder = work(
        title=title,
        author=author,
        year=year,
        work_type="bachelor_thesis",
        supervisor=supervisor,
        organization=organization,
    )
    (
        builder.section("Реферат")
        .paragraph(_PLACEHOLDER)
        .section("Введение")
        .paragraph(_PLACEHOLDER)
        .section("Глава 1. Аналитическая часть")
        .paragraph(_PLACEHOLDER)
        .section("Глава 2. Практическая часть")
        .paragraph(_PLACEHOLDER)
        .section("Заключение")
        .paragraph(_PLACEHOLDER)
        .section("Список использованных источников")
    )
    return builder


def research_report_template(
    title: str,
    year: int | None = None,
    organization: str = "",
) -> WorkBuilder:
    """Скелет отчёта о НИР по ГОСТ 7.32-2017."""
    builder = work(
        title=title,
        year=year,
        work_type="research_report",
        organization=organization,
    )
    (
        builder.section("Реферат")
        .paragraph(_PLACEHOLDER)
        .section("Введение")
        .paragraph(_PLACEHOLDER)
        .section("Основная часть")
        .paragraph(_PLACEHOLDER)
        .section("Заключение")
        .paragraph(_PLACEHOLDER)
        .section("Список использованных источников")
    )
    return builder


__all__ = [
    "bachelor_thesis_template",
    "coursework_template",
    "research_report_template",
]
