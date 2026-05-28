"""Подсчёт структурной статистики Document.

Используется командой `gostforge stats` и при желании UI-частью для
вывода краткого профиля документа: число разделов, параграфов, таблиц,
рисунков, источников и слов.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from gostforge.model import (
    Block,
    Document,
    Figure,
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
    """

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
            _iter_blocks_recursive(item.children, stats)
        elif isinstance(item, Paragraph):
            stats.paragraphs += 1
            text = "".join(r.text for r in item.content if isinstance(r, TextRun))
            if text.strip():
                stats.paragraphs_non_empty += 1
                stats.characters += len(text)
                stats.words += len(text.split())
        elif isinstance(item, Table):
            stats.tables += 1
        elif isinstance(item, Figure):
            stats.figures += 1


def compute_stats(document: Document) -> DocumentStats:
    """Собрать статистику по Document."""
    stats = DocumentStats()
    stats.page_sections = len(document.page_sections)
    stats.bibliography_entries = len(document.bibliography)
    for ps in document.page_sections:
        _iter_blocks_recursive(ps.content, stats)
    return stats
