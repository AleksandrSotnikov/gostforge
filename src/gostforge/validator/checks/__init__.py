"""Реализации проверок.

Каждая категория — в своём модуле:
- formatting.py — F.* (страница)
- text.py — T.* (основной текст)
- structure.py — S.* (структура)
- headings.py — H.* (заголовки)
- figures.py — I.* (рисунки)
- tables.py — B.* (таблицы)
- formulas.py — M.* (формулы)
- lists.py — L.* (списки)
- references.py — R.* (литература)
- crossrefs.py — C.* (перекрёстные ссылки)
- abbreviations.py — A.* (сокращения)
- appendices.py — P.* (приложения)
- page_sections.py — K.* (колонтитулы)
- volume.py — V.* (объём)
- style.py — X.* (лингвистика)
- units.py — U.* (единицы измерения, ГОСТ Р 8.000-2015)

Импорт здесь нужен, чтобы декоратор @register сработал при загрузке валидатора.
"""

from . import (  # noqa: F401
    abbreviations,
    appendices,
    crossrefs,
    figures,
    formatting,
    formulas,
    headings,
    lists,
    page_sections,
    references,
    structure,
    style,
    tables,
    text,
    units,
    volume,
)
