"""Тесты S.01 — наличие обязательных разделов."""

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


def _heading(text: str, level: int = 1) -> LogicalSection:
    return LogicalSection(
        id=f"sec-{text}",
        level=level,
        heading=[TextRun(text=text)],
    )


def _doc(sections: list[LogicalSection]) -> Document:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            content=list(sections),
        )
    )
    return doc


def test_s01_registered() -> None:
    assert "S.01" in registered_checks()


def test_s01_all_required_sections_present() -> None:
    doc = _doc(
        [
            _heading("Введение"),
            _heading("Глава 1"),
            _heading("Заключение"),
            _heading("Список использованных источников"),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.01"]
    assert found == []


def test_s01_missing_introduction() -> None:
    doc = _doc(
        [
            _heading("Глава 1"),
            _heading("Заключение"),
            _heading("Список использованных источников"),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.01"]
    assert len(found) == 1
    assert "Введение" in found[0].message


def test_s01_alias_for_bibliography() -> None:
    """«Список литературы» эквивалентно «Список использованных источников»."""
    doc = _doc(
        [
            _heading("Введение"),
            _heading("Заключение"),
            _heading("Список литературы"),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.01"]
    assert found == []


def test_s01_case_insensitive_match() -> None:
    doc = _doc(
        [
            _heading("ВВЕДЕНИЕ"),  # uppercase
            _heading("заключение"),  # lowercase
            _heading("Список использованных источников"),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.01"]
    assert found == []


def test_s01_nested_logical_sections_are_traversed() -> None:
    """Введение может быть внутри другой LogicalSection (например, обёртки)."""
    wrapper = LogicalSection(
        id="wrap",
        level=1,
        heading=[TextRun(text="Основная часть")],
        children=[
            _heading("Введение"),  # level=1, вложен
            _heading("Заключение"),
            _heading("Список использованных источников"),
        ],
    )
    doc = _doc([wrapper])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.01"]
    assert found == []


def test_s01_uses_profile_params_for_required_list() -> None:
    """checks.S.01.params.required_headings перекрывает дефолт."""
    doc = _doc([_heading("Реферат"), _heading("Введение")])
    profile = load_profile("gost-7.32-2017")
    profile.checks["S.01"].params["required_headings"] = ["Реферат", "Введение"]
    found = [v for v in validate(doc, profile) if v.check_code == "S.01"]
    assert found == []


def test_s01_violation_paragraphs_not_counted() -> None:
    """Обычный абзац с текстом «Введение» — не заголовок, нарушение остаётся."""
    paragraph = Paragraph(
        id="p1",
        content=[TextRun(text="Введение")],
        style_name="Normal",
    )
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="m",
            type="main",
            content=[paragraph],
        )
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.01"]
    # все 3 раздела отсутствуют
    assert len(found) == 3
