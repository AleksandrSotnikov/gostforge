"""Подсчёт структурной статистики Document.

Используется командой `gostforge stats` и UI-частью (панель «Прогресс
работы» Конструктора, страница «Статистика» Нормоконтроля) для вывода
краткого профиля документа: число разделов, параграфов, таблиц,
рисунков, источников, слов плюс производные метрики плотности (среднее
слов в параграфе, распределение источников по типам и т. д.).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from gostforge.model import (
    Block,
    Citation,
    CrossRef,
    Document,
    Figure,
    Formula,
    InlineFormula,
    ListBlock,
    LogicalSection,
    Paragraph,
    Table,
    TextRun,
)


@dataclass
class DocumentStats:
    """Структурная статистика документа.

    Не считаем количество физических страниц — для этого нужен рендер
    в .pdf или Word. Все остальные показатели — точные из модели.

    Новые поля (плотность контента) добавляются с default-значениями —
    back-compat сохраняется для downstream-кода, который опирается на
    конкретные поля.
    """

    # --- базовая структура ---
    page_sections: int = 0
    logical_sections_level_1: int = 0
    logical_sections_total: int = 0
    paragraphs: int = 0
    paragraphs_non_empty: int = 0
    tables: int = 0
    figures: int = 0
    bibliography_entries: int = 0
    words: int = 0
    characters: int = 0

    # --- плотность контента (расширение, август 2026-Q2) ---

    # Подразделы по уровням (level=2, level=3). level=1 уже считается в
    # logical_sections_level_1; level=4+ редок и идёт в total.
    logical_sections_level_2: int = 0
    logical_sections_level_3: int = 0

    # Списки и формулы как блоки документа.
    lists: int = 0
    list_items: int = 0
    formulas: int = 0

    # Сколько параграфов содержат inline-формулы / cross-refs / цитаты.
    paragraphs_with_inline_formula: int = 0
    paragraphs_with_xref: int = 0
    paragraphs_with_citation: int = 0

    # Распределение источников библиографии по типам:
    # {"book": N, "article": M, "web": K, ...}. Пустой словарь, если
    # библиографии нет.
    bibliography_by_type: dict[str, int] = field(default_factory=dict)

    @property
    def avg_words_per_paragraph(self) -> float:
        """Среднее число слов в непустом параграфе. 0.0 если параграфов нет.

        Помогает обнаружить «параграфы-заглушки» (если среднее ≤ 5,
        работа похожа на каркас, а не заполненный документ) и
        наоборот «параграфы-простыни» (≥ 60 слов — рекомендуется
        разбить на несколько).
        """
        if self.paragraphs_non_empty == 0:
            return 0.0
        return round(self.words / self.paragraphs_non_empty, 1)


def _iter_blocks_recursive(
    items: Sequence[LogicalSection | Block],
    stats: DocumentStats,
) -> None:
    """Рекурсивно обойти содержимое и обновить счётчики stats."""
    for item in items:
        if isinstance(item, LogicalSection):
            stats.logical_sections_total += 1
            if item.level == 1:
                stats.logical_sections_level_1 += 1
            elif item.level == 2:
                stats.logical_sections_level_2 += 1
            elif item.level == 3:
                stats.logical_sections_level_3 += 1
            _iter_blocks_recursive(item.children, stats)
        elif isinstance(item, Paragraph):
            stats.paragraphs += 1
            text_runs = [r for r in item.content if isinstance(r, TextRun)]
            text = "".join(r.text for r in text_runs)
            if text.strip():
                stats.paragraphs_non_empty += 1
                stats.characters += len(text)
                stats.words += len(text.split())
            # Inline-элементы: формула / xref / цитата. Считаем
            # параграфы, в которых они есть, по флагу (одного достаточно).
            has_formula = any(isinstance(el, InlineFormula) for el in item.content)
            has_xref = any(isinstance(el, CrossRef) for el in item.content)
            has_citation = any(isinstance(el, Citation) for el in item.content)
            if has_formula:
                stats.paragraphs_with_inline_formula += 1
            if has_xref:
                stats.paragraphs_with_xref += 1
            if has_citation:
                stats.paragraphs_with_citation += 1
        elif isinstance(item, Table):
            stats.tables += 1
        elif isinstance(item, Figure):
            stats.figures += 1
        elif isinstance(item, ListBlock):
            stats.lists += 1
            stats.list_items += len(item.items)
        elif isinstance(item, Formula):
            stats.formulas += 1


def compute_stats(document: Document) -> DocumentStats:
    """Собрать статистику по Document."""
    stats = DocumentStats()
    stats.page_sections = len(document.page_sections)
    stats.bibliography_entries = len(document.bibliography)

    # Распределение источников по типам.
    by_type: dict[str, int] = {}
    for entry in document.bibliography:
        # entry.type — Literal["book", "article", "web", ...].
        t = str(entry.type)
        by_type[t] = by_type.get(t, 0) + 1
    stats.bibliography_by_type = by_type

    for ps in document.page_sections:
        _iter_blocks_recursive(ps.content, stats)
    return stats


def compute_per_section_stats(document: Document) -> list[tuple[str, DocumentStats]]:
    """Статистика отдельно по каждому top-level разделу документа.

    Полезно, чтобы увидеть наполненность по главам: какие пустые,
    какие перегружены таблицами, где мало источников и т. д.

    Возвращает список ``(heading, stats)`` в порядке появления в
    документе. `stats.bibliography_entries` — 0 для всех (библиография
    в модели хранится отдельно от секций, не привязана к конкретной
    главе); `bibliography_by_type` — пустой словарь.

    Top-level раздел — `LogicalSection` уровня 1 внутри любого
    `PageSection`. Контент верхнего уровня без обёртки в раздел
    (например, оглавление-как-блок) идёт в группу `"(без раздела)"`.
    """
    result: list[tuple[str, DocumentStats]] = []
    for ps in document.page_sections:
        # Блоки до первого LogicalSection идут в пред-разделовую группу.
        orphan = DocumentStats()
        has_orphan = False
        for item in ps.content:
            if isinstance(item, LogicalSection):
                if item.level != 1:
                    # Уровень 2+ без обёртки в level-1 — экзотика, считаем
                    # его как top-level «раздел» с этим heading.
                    pass
                section_stats = DocumentStats()
                # Сам heading-параграф не считается параграфом контента,
                # его пропускаем — учитываем только children.
                _iter_blocks_recursive(item.children, section_stats)
                heading_text = "".join(
                    r.text for r in item.heading if isinstance(r, TextRun)
                ).strip()
                result.append((heading_text or "(без названия)", section_stats))
            else:
                # Параграф/таблица/рисунок до первого LogicalSection.
                _iter_blocks_recursive([item], orphan)
                has_orphan = True
        if has_orphan:
            result.append(("(без раздела)", orphan))
    return result
