"""Конструктор работ — fluent API над моделью документа.

Высокоуровневый интерфейс для программной сборки курсовых, ВКР и отчётов:
студент описывает работу декларативно через `work(...).section(...)...`,
а конструктор сам ставит правильные поля, колонтитулы, нумерацию и
`page_break_before` у заголовков, чтобы результат проходил профильные
проверки из коробки.
"""

from .section_builder import SectionBuilder
from .work_builder import WorkBuilder, work

__all__ = ["SectionBuilder", "WorkBuilder", "work"]
