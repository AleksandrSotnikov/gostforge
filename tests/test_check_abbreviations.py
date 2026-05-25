"""Тесты A.01 — расшифровка аббревиатур при первом употреблении."""

# ruff: noqa: RUF003

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
        id="main",
        name="m",
        type="main",
        content=list(items),  # type: ignore[arg-type]
    )
    doc.page_sections.append(page_section)
    return doc


def test_a01_registered() -> None:
    assert "A.01" in registered_checks()


def test_a01_expanded_before_abbr_no_violation() -> None:
    """«Программное обеспечение (ПО)» — расшифровка перед, нет нарушения."""
    para = Paragraph(
        id="p-1",
        content=[
            TextRun(
                text="Программное обеспечение (ПО) разрабатывается по ГОСТ."
            )
        ],
    )
    doc = _doc_with_content([para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert found == []


def test_a01_expanded_after_abbr_no_violation() -> None:
    """«ПО (программное обеспечение)» — расшифровка после, нет нарушения."""
    para = Paragraph(
        id="p-1",
        content=[
            TextRun(text="ПО (программное обеспечение) включает несколько модулей.")
        ],
    )
    doc = _doc_with_content([para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert found == []


def test_a01_unexplained_abbr_violation() -> None:
    """«ПО используется...» — без расшифровки — warning."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="ПО используется для обработки данных.")],
    )
    doc = _doc_with_content([para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["abbreviation"] == "ПО"


def test_a01_known_abbreviations_skipped() -> None:
    """ГОСТ, URL и другие известные — пропускаются без расшифровки."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="По ГОСТ 7.32 ссылка на URL обязательна.")],
    )
    doc = _doc_with_content([para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert found == []


def test_a01_custom_known_abbreviations_param() -> None:
    """Параметр `known_abbreviations` расширяет список известных."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="МГУ — крупный университет.")],
    )
    doc = _doc_with_content([para])
    profile = load_profile("gost-7.32-2017")
    # Без параметра — было бы нарушение.
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert len(found) == 1
    # С параметром «МГУ» — нарушения нет.
    profile.checks["A.01"].params["known_abbreviations"] = ["МГУ"]
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert found == []


def test_a01_only_first_use_checked() -> None:
    """После расшифровки повторные употребления АББР — без нарушения."""
    para1 = Paragraph(
        id="p-1",
        content=[TextRun(text="Программное обеспечение (ПО) — это код.")],
    )
    para2 = Paragraph(
        id="p-2",
        content=[TextRun(text="ПО разрабатывается командой.")],
    )
    doc = _doc_with_content([para1, para2])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert found == []


def test_a01_abbr_in_nested_section() -> None:
    """Аббревиатура в вложенной секции тоже проверяется."""
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Под")],
        children=[
            Paragraph(
                id="p-1",
                content=[TextRun(text="БД содержит таблицы.")],
            )
        ],
    )
    doc = _doc_with_content([inner])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "A.01"]
    assert len(found) == 1
    assert found[0].details["abbreviation"] == "БД"
