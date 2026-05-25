"""Тесты P.01 — маркировка приложений без запрещённых букв."""

# ruff: noqa: RUF001, RUF002

from gostforge.model import (
    Document,
    LogicalSection,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _doc_with_content(items: list[object]) -> Document:
    doc = Document()
    page_section = PageSection(
        id="appendix",
        name="app",
        type="appendix",
        content=list(items),  # type: ignore[arg-type]
    )
    doc.page_sections.append(page_section)
    return doc


def _appendix(section_id: str, title: str) -> LogicalSection:
    """Удобный конструктор приложения уровня 1 с заданным заголовком."""
    return LogicalSection(
        id=section_id,
        level=1,
        heading=[TextRun(text=title)],
        children=[Paragraph(id=f"p-{section_id}", content=[TextRun(text="...")])],
    )


def test_p01_registered() -> None:
    assert "P.01" in registered_checks()


def test_p01_correct_sequence_no_violation() -> None:
    """Приложение А, Б, В — корректная последовательность, нет нарушений."""
    sections = [
        _appendix("app-a", "Приложение А"),
        _appendix("app-b", "Приложение Б"),
        _appendix("app-c", "Приложение В"),
    ]
    doc = _doc_with_content(list(sections))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert found == []


def test_p01_forbidden_letter_violation() -> None:
    """Приложение Ё — запрещённая буква, нарушение."""
    sections = [
        _appendix("app-a", "Приложение А"),
        _appendix("app-yo", "Приложение Ё"),
    ]
    doc = _doc_with_content(list(sections))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert any(
        v.details.get("letter") == "Ё" and "запрещённая" in v.message
        for v in found
    )


def test_p01_gap_in_sequence_violation() -> None:
    """Приложение А → В (пропуск Б) — нарушение порядка."""
    sections = [
        _appendix("app-a", "Приложение А"),
        _appendix("app-c", "Приложение В"),
    ]
    doc = _doc_with_content(list(sections))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert found[0].details["expected"] == "Б"
    assert found[0].details["found"] == "В"


def test_p01_latin_letter_violation() -> None:
    """Приложение A (латинская) — нарушение «латинская буква»."""
    section = _appendix("app-a", "Приложение A")
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert "латинской" in found[0].message


def test_p01_lowercase_letter_violation() -> None:
    """Приложение а (строчная) — нарушение «строчная»."""
    section = _appendix("app-a", "Приложение а")
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert "строчной" in found[0].message


def test_p01_not_starting_from_a_violation() -> None:
    """Первое приложение — Б — нарушение (должно начинаться с А)."""
    section = _appendix("app-b", "Приложение Б")
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert found[0].details["expected"] == "А"


def test_p01_no_appendices_no_violation() -> None:
    """Документ без приложений — никаких нарушений P.01."""
    doc = _doc_with_content([])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert found == []
