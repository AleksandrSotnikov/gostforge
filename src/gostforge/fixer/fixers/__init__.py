"""Реализации фиксеров.

Каждая категория — в своём модуле:
- text.py — T.* (основной текст)
- headings.py — H.* (заголовки)
- lists.py — L.* (списки)
- formatting.py — F.* (страница, нумерация)

Импорт здесь нужен, чтобы декоратор @register сработал при загрузке модуля.
"""

from . import formatting, headings, lists, text  # noqa: F401
