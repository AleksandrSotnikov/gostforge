# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты сессии 4 плана развития:
* X.05 — терминологическая консистентность (реализация);
* B.10 — пустые таблицы.
"""

from __future__ import annotations

import pytest

from gostforge.model import (
    Document,
    DocumentMetadata,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate


def _doc_with_paragraph(text: str) -> Document:
    doc = Document(metadata=DocumentMetadata(title="X"))
    p = Paragraph(
        id="p1",
        content=[TextRun(text=text)],
        style_name="Normal",
    )
    sec = LogicalSection(
        id="s",
        heading=[TextRun(text="Введение")],
        level=1,
        children=[p],
    )
    doc.page_sections.append(
        PageSection(
            id="m", name="N", type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec],
        )
    )
    return doc


# --- X.05 терминологическая консистентность ---


def test_x05_no_terms_in_profile_no_violation() -> None:
    """Без params.terms — нет нарушений (по умолчанию проверка пустая)."""
    doc = _doc_with_paragraph("База данных оптимизирована. БД работает быстро.")
    profile = load_profile("gost-7.32-2017")
    # X.05 в дефолтном профиле без params.terms.
    v = validate(doc, profile)
    x05 = [x for x in v if x.check_code == "X.05"]
    assert x05 == []


def test_x05_detects_canonical_and_alias_mixed() -> None:
    """Используется и canonical, и alias — нарушение."""
    doc = _doc_with_paragraph("База данных оптимизирована. БД работает быстро.")
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["X.05"].params = {
        "terms": [
            {"canonical": "база данных", "aliases": ["БД"]},
        ]
    }
    v = validate(doc, profile)
    x05 = [x for x in v if x.check_code == "X.05"]
    assert len(x05) == 1
    assert "БД" in x05[0].message
    assert "база данных" in x05[0].message


def test_x05_detects_only_alias() -> None:
    """Используется только alias — тоже нарушение (рекомендуем canonical)."""
    doc = _doc_with_paragraph("Используется БД для хранения.")
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["X.05"].params = {
        "terms": [
            {"canonical": "база данных", "aliases": ["БД"]},
        ]
    }
    v = validate(doc, profile)
    x05 = [x for x in v if x.check_code == "X.05"]
    assert len(x05) == 1


def test_x05_only_canonical_no_violation() -> None:
    """Используется только canonical — нет нарушений."""
    doc = _doc_with_paragraph("База данных оптимизирована для скорости.")
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["X.05"].params = {
        "terms": [{"canonical": "база данных", "aliases": ["БД"]}]
    }
    v = validate(doc, profile)
    x05 = [x for x in v if x.check_code == "X.05"]
    assert x05 == []


def test_x05_multiple_terms() -> None:
    """Несколько терминов проверяются независимо."""
    doc = _doc_with_paragraph(
        "Используем БД и ПО для разработки. База данных и ПО."
    )
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["X.05"].params = {
        "terms": [
            {"canonical": "база данных", "aliases": ["БД"]},
            {"canonical": "программное обеспечение", "aliases": ["ПО"]},
        ]
    }
    v = validate(doc, profile)
    x05 = [x for x in v if x.check_code == "X.05"]
    # Один — БД vs «база данных», второй — только «ПО» без canonical.
    assert len(x05) == 2


def test_x05_case_insensitive() -> None:
    """Проверка регистронезависима: «бд» = «БД» = «Бд»."""
    doc = _doc_with_paragraph("В системе бд оптимизирована.")
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["X.05"].params = {
        "terms": [{"canonical": "база данных", "aliases": ["БД"]}]
    }
    v = validate(doc, profile)
    x05 = [x for x in v if x.check_code == "X.05"]
    assert len(x05) == 1


def test_x05_invalid_params_graceful() -> None:
    """Невалидный params (без canonical/aliases) — не падает."""
    doc = _doc_with_paragraph("текст")
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.checks["X.05"].params = {
        "terms": [
            {"canonical": ""},
            {"aliases": ["X"]},
            "not-a-dict",
        ]
    }
    v = validate(doc, profile)
    x05 = [x for x in v if x.check_code == "X.05"]
    # Все три записи невалидны — пропускаются молча.
    assert x05 == []


# --- B.10 пустые таблицы ---


def _doc_with_table(table: Table) -> Document:
    doc = Document(metadata=DocumentMetadata(title="X"))
    sec = LogicalSection(
        id="s",
        heading=[TextRun(text="Введение")],
        level=1,
        children=[table],
    )
    doc.page_sections.append(
        PageSection(
            id="m", name="N", type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec],
        )
    )
    return doc


def test_b10_no_rows_is_empty() -> None:
    """Таблица только с заголовками, без строк данных — пустая."""
    t = Table(
        id="t",
        caption=[TextRun(text="Test")],
        headers=[[TextRun(text="A")], [TextRun(text="B")]],
        rows=[],
    )
    doc = _doc_with_table(t)
    v = validate(doc, load_profile("gost-7.32-2017"))
    b10 = [x for x in v if x.check_code == "B.10"]
    assert len(b10) == 1


def test_b10_whitespace_only_is_empty() -> None:
    """Строки с одними пробельными ячейками — таблица пустая."""
    t = Table(
        id="t",
        caption=[TextRun(text="T")],
        headers=[[TextRun(text="A")]],
        rows=[[[TextRun(text="   ")]], [[TextRun(text="")]]],
    )
    doc = _doc_with_table(t)
    v = validate(doc, load_profile("gost-7.32-2017"))
    b10 = [x for x in v if x.check_code == "B.10"]
    assert len(b10) == 1


def test_b10_one_filled_cell_not_empty() -> None:
    """Хотя бы одна непустая ячейка — таблица не пуста."""
    t = Table(
        id="t",
        caption=[TextRun(text="T")],
        headers=[[TextRun(text="A")], [TextRun(text="B")]],
        rows=[[[TextRun(text="x")], [TextRun(text="")]]],
    )
    doc = _doc_with_table(t)
    v = validate(doc, load_profile("gost-7.32-2017"))
    b10 = [x for x in v if x.check_code == "B.10"]
    assert b10 == []


def test_b10_empty_table_uses_caption_in_message() -> None:
    """Сообщение содержит caption таблицы для идентификации."""
    t = Table(
        id="t",
        caption=[TextRun(text="Параметры эксперимента")],
        headers=[[TextRun(text="A")]],
        rows=[],
    )
    doc = _doc_with_table(t)
    v = validate(doc, load_profile("gost-7.32-2017"))
    b10 = [x for x in v if x.check_code == "B.10"]
    assert len(b10) == 1
    assert "Параметры эксперимента" in b10[0].message
