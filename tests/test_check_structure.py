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


# --- S.06 -------------------------------------------------------------------


def _section_with_paragraph(
    heading_text: str,
    *,
    page_break_before: bool | None,
    level: int = 1,
) -> LogicalSection:
    """LogicalSection с одним Paragraph внутри, у которого задан page_break_before."""
    return LogicalSection(
        id=f"sec-{heading_text}",
        level=level,
        heading=[TextRun(text=heading_text)],
        children=[
            Paragraph(
                id=f"p-{heading_text}",
                content=[TextRun(text="Текст раздела.")],
                style_name="Normal",
                page_break_before=page_break_before,
            )
        ],
    )


def test_s06_registered() -> None:
    assert "S.06" in registered_checks()


def test_s06_all_sections_have_break_no_violation() -> None:
    """У всех разделов 1 уровня (кроме первого) — page_break_before=True."""
    doc = _doc(
        [
            _section_with_paragraph("Введение", page_break_before=True),
            _section_with_paragraph("Глава 1", page_break_before=True),
            _section_with_paragraph("Заключение", page_break_before=True),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.06"]
    assert found == []


def test_s06_missing_break_violation() -> None:
    """page_break_before=False у не-первого раздела — нарушение."""
    doc = _doc(
        [
            _section_with_paragraph("Введение", page_break_before=True),
            _section_with_paragraph("Глава 1", page_break_before=False),
            _section_with_paragraph("Заключение", page_break_before=True),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.06"]
    assert len(found) == 1
    assert "Глава 1" in found[0].message


def test_s06_first_section_skipped_even_if_no_break() -> None:
    """Первый раздел 1 уровня — на первой странице, разрыв не нужен."""
    doc = _doc(
        [
            _section_with_paragraph("Введение", page_break_before=False),
            _section_with_paragraph("Заключение", page_break_before=True),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.06"]
    assert found == []


def test_s06_inherited_break_is_not_violation() -> None:
    """page_break_before=None (унаследовано) — мягкая семантика, не нарушение."""
    doc = _doc(
        [
            _section_with_paragraph("Введение", page_break_before=True),
            _section_with_paragraph("Глава 1", page_break_before=None),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.06"]
    assert found == []


def test_s06_other_levels_ignored() -> None:
    """По умолчанию required_for_level=1; уровень 2 не проверяется."""
    doc = _doc(
        [
            _section_with_paragraph("Введение", page_break_before=True),
            _section_with_paragraph("1.1 Подраздел", page_break_before=False, level=2),
            _section_with_paragraph("1.2 Подраздел", page_break_before=False, level=2),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.06"]
    assert found == []


def test_s06_required_for_level_param() -> None:
    """Параметр required_for_level=2 — проверяем уровень 2."""
    doc = _doc(
        [
            _section_with_paragraph("Введение", page_break_before=True),
            _section_with_paragraph("1.1 Первый подраздел", page_break_before=True, level=2),
            _section_with_paragraph("1.2 Второй подраздел", page_break_before=False, level=2),
        ]
    )
    profile = load_profile("gost-7.32-2017")
    profile.checks["S.06"].params["required_for_level"] = 2
    found = [v for v in validate(doc, profile) if v.check_code == "S.06"]
    assert len(found) == 1
    assert "1.2 Второй подраздел" in found[0].message


def test_s06_section_without_paragraph_skipped() -> None:
    """Раздел без Paragraph в children — пропускается (нет, что проверять)."""
    empty_section = LogicalSection(
        id="sec-empty",
        level=1,
        heading=[TextRun(text="Пустой раздел")],
    )
    doc = _doc(
        [
            _section_with_paragraph("Введение", page_break_before=True),
            empty_section,
        ]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "S.06"]
    assert found == []
