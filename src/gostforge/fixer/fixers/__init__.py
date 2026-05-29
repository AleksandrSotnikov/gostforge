"""Реализации фиксеров.

Каждая категория — в своём модуле:
- text.py — T.* (основной текст)
- headings.py — H.* (заголовки)
- lists.py — L.* (списки)
- formatting.py — F.* (страница, нумерация)
- page_sections.py — K.* (колонтитулы и нумерация секций)

Импорт здесь нужен, чтобы декоратор @register сработал при загрузке модуля.
"""

from . import formatting, headings, lists, page_sections, text  # noqa: F401
