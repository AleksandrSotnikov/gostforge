"""V.* — проверки объёма и метрик документа."""

from __future__ import annotations

from typing import Any

from gostforge.model import (
    Block,
    BlockType,
    CrossRef,
    Document,
    InlineElement,
    ListBlock,
    LogicalSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import Violation, register


def _params(profile: Profile, code: str) -> dict[str, Any]:
    cfg = profile.checks.get(code)
    if cfg is None:
        return {}
    return dict(cfg.params)


def _inline_text(elements: list[InlineElement]) -> str:
    """Склейка inline-элементов в строку."""
    parts: list[str] = []
    for el in elements:
        if isinstance(el, TextRun):
            parts.append(el.text)
        elif isinstance(el, CrossRef):
            parts.append(el.display_template)
    return "".join(parts)


def _count_words_in_section(section: LogicalSection) -> int:
    """Рекурсивно посчитать слова во всём содержимом раздела (включая вложенные)."""
    total = 0
    for child in section.children:
        if isinstance(child, LogicalSection):
            total += _count_words_in_section(child)
            continue
        if isinstance(child, Paragraph):
            text = _inline_text(child.content)
            if text.strip():
                total += len(text.split())
            continue
        if isinstance(child, Table):
            text = _inline_text(child.caption)
            if text.strip():
                total += len(text.split())
            continue
        if isinstance(child, ListBlock):
            for item in child.items:
                text = _inline_text(item)
                if text.strip():
                    total += len(text.split())
            continue
        # Прочие блоки (Figure, Formula, Code, Footnote) — без вклада в слова.
        if isinstance(child, Block) and child.type == BlockType.LIST:
            # на всякий случай (если ListBlock не словился по isinstance)
            pass
    return total


def _iter_all_logical_sections(document: Document) -> list[LogicalSection]:
    """Все LogicalSection первого уровня из всех PageSection (рекурсивно: и вложенные)."""
    result: list[LogicalSection] = []

    def walk(items: list[LogicalSection | Block]) -> None:
        for it in items:
            if isinstance(it, LogicalSection):
                result.append(it)
                walk(it.children)

    for page_section in document.page_sections:
        walk(page_section.content)
    return result


def _find_section_by_heading(document: Document, *needles: str) -> LogicalSection | None:
    """Найти LogicalSection по заголовку (case-insensitive, точное совпадение после strip)."""
    needles_lower = {n.lower() for n in needles}
    for section in _iter_all_logical_sections(document):
        heading = _inline_text(section.heading).strip().lower()
        if heading in needles_lower:
            return section
    return None


@register("V.01")
def check_total_volume(document: Document, profile: Profile) -> list[Violation]:
    """V.01 — общий объём документа.

    Эвристика: число страниц = слова / words_per_page. Если оценка выходит
    за пределы [min_pages, max_pages] — выпускается warning.
    """
    # Импорт внутри функции, чтобы избежать возможных циклов на уровне модуля.
    from gostforge.stats import compute_stats

    params = _params(profile, "V.01")
    min_pages = int(params.get("min_pages", 25))
    max_pages = int(params.get("max_pages", 50))
    words_per_page = int(params.get("words_per_page", 250))
    if words_per_page <= 0:
        words_per_page = 250

    stats = compute_stats(document)
    pages_est = stats.words / words_per_page

    violations: list[Violation] = []
    if pages_est < min_pages:
        violations.append(
            Violation(
                check_code="V.01",
                severity="warning",
                message=(
                    f"Объём документа оценён в ~{pages_est:.1f} страниц (минимум — {min_pages})"
                ),
                location="document",
                suggestion=f"Дописать материал до ~{min_pages} страниц",
                details={
                    "words": str(stats.words),
                    "pages_est": f"{pages_est:.2f}",
                    "min_pages": str(min_pages),
                    "max_pages": str(max_pages),
                },
            )
        )
    elif pages_est > max_pages:
        violations.append(
            Violation(
                check_code="V.01",
                severity="warning",
                message=(
                    f"Объём документа оценён в ~{pages_est:.1f} страниц (максимум — {max_pages})"
                ),
                location="document",
                suggestion=f"Сократить материал до ~{max_pages} страниц",
                details={
                    "words": str(stats.words),
                    "pages_est": f"{pages_est:.2f}",
                    "min_pages": str(min_pages),
                    "max_pages": str(max_pages),
                },
            )
        )
    return violations


@register("V.02")
def check_intro_conclusion_volume(document: Document, profile: Profile) -> list[Violation]:
    """V.02 — объём введения и заключения.

    Ищет логические разделы с заголовком «Введение» и «Заключение»
    (case-insensitive). Если число слов выходит за рамки коридора —
    выпускается warning. Если раздел отсутствует, проверка молчит:
    наличие разделов контролирует другая проверка (S.*).
    """
    params = _params(profile, "V.02")
    intro_min = int(params.get("intro_min_words", 800))
    intro_max = int(params.get("intro_max_words", 1500))
    conclusion_min = int(params.get("conclusion_min_words", 500))
    conclusion_max = int(params.get("conclusion_max_words", 1200))

    violations: list[Violation] = []

    intro = _find_section_by_heading(document, "Введение")
    if intro is not None:
        words = _count_words_in_section(intro)
        if words < intro_min:
            violations.append(
                Violation(
                    check_code="V.02",
                    severity="warning",
                    message=(f"Введение содержит {words} слов (минимум — {intro_min})"),
                    location=f"logical_sections.{intro.id}",
                    suggestion=f"Расширить введение до {intro_min} слов",
                    details={
                        "section": "Введение",
                        "words": str(words),
                        "min": str(intro_min),
                        "max": str(intro_max),
                    },
                )
            )
        elif words > intro_max:
            violations.append(
                Violation(
                    check_code="V.02",
                    severity="warning",
                    message=(f"Введение содержит {words} слов (максимум — {intro_max})"),
                    location=f"logical_sections.{intro.id}",
                    suggestion=f"Сократить введение до {intro_max} слов",
                    details={
                        "section": "Введение",
                        "words": str(words),
                        "min": str(intro_min),
                        "max": str(intro_max),
                    },
                )
            )

    conclusion = _find_section_by_heading(document, "Заключение")
    if conclusion is not None:
        words = _count_words_in_section(conclusion)
        if words < conclusion_min:
            violations.append(
                Violation(
                    check_code="V.02",
                    severity="warning",
                    message=(f"Заключение содержит {words} слов (минимум — {conclusion_min})"),
                    location=f"logical_sections.{conclusion.id}",
                    suggestion=f"Расширить заключение до {conclusion_min} слов",
                    details={
                        "section": "Заключение",
                        "words": str(words),
                        "min": str(conclusion_min),
                        "max": str(conclusion_max),
                    },
                )
            )
        elif words > conclusion_max:
            violations.append(
                Violation(
                    check_code="V.02",
                    severity="warning",
                    message=(f"Заключение содержит {words} слов (максимум — {conclusion_max})"),
                    location=f"logical_sections.{conclusion.id}",
                    suggestion=f"Сократить заключение до {conclusion_max} слов",
                    details={
                        "section": "Заключение",
                        "words": str(words),
                        "min": str(conclusion_min),
                        "max": str(conclusion_max),
                    },
                )
            )

    return violations


@register("V.03")
def check_theory_practice_ratio(document: Document, profile: Profile) -> list[Violation]:
    """V.03 — соотношение теории и практики (заглушка, severity=info).

    На Фазе 1 пока не реализована: требуется классификация разделов
    по их характеру (теоретический/практический/смешанный) и более
    тонкий учёт глубины. TODO Phase 2.
    """
    # Используем аргументы, чтобы линтер не ругался на "unused".
    _ = document
    _ = profile
    return []


@register("V.04")
def check_figures_tables_density(document: Document, profile: Profile) -> list[Violation]:
    """V.04 — плотность рисунков и таблиц.

    На каждые 10 «страниц» (оценка по формуле V.01) должно быть как минимум
    1 рисунок и 1 таблица. Severity = info: для коротких пояснительных
    записок такое требование может не выполняться объективно.
    """
    from gostforge.stats import compute_stats

    params = _params(profile, "V.04")
    min_figures_per_10 = int(params.get("min_figures_per_10_pages", 1))
    min_tables_per_10 = int(params.get("min_tables_per_10_pages", 1))

    # Эвристика страниц — единая с V.01.
    v01_params = _params(profile, "V.01")
    words_per_page = int(v01_params.get("words_per_page", 250))
    if words_per_page <= 0:
        words_per_page = 250

    stats = compute_stats(document)
    pages_est = stats.words / words_per_page
    blocks_of_ten = max(pages_est / 10.0, 1.0)  # минимум 1 блок, иначе делим на 0

    expected_figures = min_figures_per_10 * blocks_of_ten
    expected_tables = min_tables_per_10 * blocks_of_ten

    violations: list[Violation] = []
    if stats.figures < expected_figures:
        violations.append(
            Violation(
                check_code="V.04",
                severity="info",
                message=(
                    f"Рисунков: {stats.figures} при оценке "
                    f"~{pages_est:.1f} страниц "
                    f"(ожидается не менее {expected_figures:.1f})"
                ),
                location="document",
                suggestion="Добавить иллюстрации, поясняющие материал",
                details={
                    "figures": str(stats.figures),
                    "pages_est": f"{pages_est:.2f}",
                    "expected": f"{expected_figures:.2f}",
                },
            )
        )
    if stats.tables < expected_tables:
        violations.append(
            Violation(
                check_code="V.04",
                severity="info",
                message=(
                    f"Таблиц: {stats.tables} при оценке "
                    f"~{pages_est:.1f} страниц "
                    f"(ожидается не менее {expected_tables:.1f})"
                ),
                location="document",
                suggestion="Добавить таблицы, систематизирующие материал",
                details={
                    "tables": str(stats.tables),
                    "pages_est": f"{pages_est:.2f}",
                    "expected": f"{expected_tables:.2f}",
                },
            )
        )
    return violations
