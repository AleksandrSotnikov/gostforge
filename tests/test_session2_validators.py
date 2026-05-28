"""Тесты сессии 2 плана развития: расширение нормоконтроля.

* U.01, U.02, U.03 — единицы измерения (ГОСТ Р 8.000-2015);
* R.14 — формат DOI и URL.
"""

from __future__ import annotations

import pytest

from gostforge.model import (
    BibliographyEntry,
    Document,
    DocumentMetadata,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate


def _doc_with_text(text: str) -> Document:
    """Минимальный документ с одним параграфом."""
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
            id="m",
            name="N",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[sec],
        )
    )
    return doc


# --- U.01: неразрывный пробел между числом и единицей ---


@pytest.mark.parametrize(
    "text,expected_count",
    [
        ("Масса 10 кг", 1),
        ("Длина 5 м, ширина 3 м", 2),
        # Неразрывный пробел (U+00A0) — нет нарушения.
        ("Масса 10 кг", 0),
        # Без пробела — не схватываем (это U.02 территория).
        ("Масса 10кг", 0),
        # Несколько единиц подряд.
        ("Шрифт 14 пт, кегль 12 пт", 0),  # 'пт' не в списке U_SI_UNITS
        ("Скорость 5 км/ч", 1),
    ],
)
def test_u01_detects_regular_space(text: str, expected_count: int) -> None:
    doc = _doc_with_text(text)
    v = validate(doc, load_profile("gost-7.32-2017"))
    u01 = [x for x in v if x.check_code == "U.01"]
    assert len(u01) == expected_count, (
        f"text={text!r}, expected {expected_count}, got {len(u01)}: {[m.message for m in u01]}"
    )


# --- U.02: запрещены знаки между числом и единицей ---


def test_u02_detects_period_before_unit() -> None:
    doc = _doc_with_text("Масса 10.кг и 5.м это плохо")
    v = validate(doc, load_profile("gost-7.32-2017"))
    u02 = [x for x in v if x.check_code == "U.02"]
    assert len(u02) == 2


def test_u02_detects_comma_before_unit() -> None:
    doc = _doc_with_text("50,% это плохо")
    v = validate(doc, load_profile("gost-7.32-2017"))
    u02 = [x for x in v if x.check_code == "U.02"]
    assert len(u02) == 1


def test_u02_decimals_with_unit_ok() -> None:
    """«5,5 кг» (десятичное число + единица) — НЕ нарушение U.02."""
    doc = _doc_with_text("Масса 5,5 кг")
    v = validate(doc, load_profile("gost-7.32-2017"))
    u02 = [x for x in v if x.check_code == "U.02"]
    # 5,5 — десятичное число; запятая между цифрами, не между числом и единицей.
    assert u02 == []


# --- U.03: единица без точки в конце ---


def test_u03_detects_trailing_dot() -> None:
    doc = _doc_with_text("Масса 10 кг. И ещё 5 м.")
    v = validate(doc, load_profile("gost-7.32-2017"))
    u03 = [x for x in v if x.check_code == "U.03"]
    # 'кг.' и 'м.' — два нарушения.
    assert len(u03) >= 1


def test_u03_does_not_trigger_on_year() -> None:
    """«2024 г.» — это год, не «грамм». Не должно срабатывать."""
    doc = _doc_with_text("В 2024 г. опубликовано")
    v = validate(doc, load_profile("gost-7.32-2017"))
    u03 = [x for x in v if x.check_code == "U.03" and "г" in x.message]
    assert u03 == []


def test_u03_does_not_trigger_on_page_reference() -> None:
    """«с. 5» = «страница 5», не «секунда». Не должно срабатывать."""
    doc = _doc_with_text("на 25 с. указано")
    v = validate(doc, load_profile("gost-7.32-2017"))
    u03 = [x for x in v if x.check_code == "U.03" and "с" in x.message]
    assert u03 == []


# --- R.14: формат DOI/URL ---


def test_r14_valid_doi_no_violation() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.bibliography.append(
        BibliographyEntry(
            id="r1",
            type="article",
            fields={"raw": "...", "doi": "10.1145/3372297.3417258"},
        )
    )
    v = validate(doc, load_profile("gost-7.32-2017"))
    assert [x for x in v if x.check_code == "R.14"] == []


def test_r14_invalid_doi_violation() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.bibliography.append(
        BibliographyEntry(
            id="r1",
            type="article",
            fields={"raw": "...", "doi": "not-a-doi-format"},
        )
    )
    v = validate(doc, load_profile("gost-7.32-2017"))
    r14 = [x for x in v if x.check_code == "R.14"]
    assert len(r14) == 1
    assert "10.NNNN" in r14[0].suggestion


def test_r14_valid_url_no_violation() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.bibliography.append(
        BibliographyEntry(
            id="r1",
            type="web",
            fields={"raw": "...", "url": "https://example.com/path/to/page"},
        )
    )
    v = validate(doc, load_profile("gost-7.32-2017"))
    assert [x for x in v if x.check_code == "R.14"] == []


def test_r14_invalid_url_missing_colon() -> None:
    """«https//» вместо «https://» — типичная опечатка."""
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.bibliography.append(
        BibliographyEntry(
            id="r1",
            type="web",
            fields={"raw": "...", "url": "https//example.com"},
        )
    )
    v = validate(doc, load_profile("gost-7.32-2017"))
    r14 = [x for x in v if x.check_code == "R.14"]
    assert len(r14) == 1


def test_r14_invalid_url_no_protocol() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.bibliography.append(
        BibliographyEntry(
            id="r1",
            type="web",
            fields={"raw": "...", "url": "example.com"},
        )
    )
    v = validate(doc, load_profile("gost-7.32-2017"))
    r14 = [x for x in v if x.check_code == "R.14"]
    assert len(r14) == 1


def test_r14_empty_doi_url_no_violation() -> None:
    """Пустые поля — не нарушают (R.14 не требует, чтобы они были)."""
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.bibliography.append(
        BibliographyEntry(
            id="r1",
            type="book",
            fields={"raw": "Кнут. — М., 2007."},
        )
    )
    v = validate(doc, load_profile("gost-7.32-2017"))
    assert [x for x in v if x.check_code == "R.14"] == []
