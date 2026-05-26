# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты на отключение проверок для отдельных логических разделов.

Фича конструктора: студент может пометить раздел (титульный лист,
реферат, приложения) как «не подчиняющийся правилам ГОСТа» — указав
конкретные коды проверок или ``"*"`` (отключить все). Реализация:

* ``LogicalSection.disabled_checks: list[str]`` — список кодов или ``["*"]``.
* ``engine.validate()`` фильтрует Violations, у которых location
  содержит id раздела с этим кодом в disabled_checks.
* Builder API: ``.skip_checks(*codes)`` и ``.skip_all_checks()``.
"""

from __future__ import annotations

from gostforge.builder import work
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
from gostforge.validator.engine import (
    Violation,
    _filter_disabled_section_violations,
)


# --- _filter_disabled_section_violations — чистая функция ---


def _make_doc_with_section(disabled_checks: list[str]) -> Document:
    """Минимальный Document с одной LogicalSection и заданными disabled_checks."""
    section = LogicalSection(
        id="sec-titul",
        heading=[TextRun(text="Титульный")],
        level=1,
        disabled_checks=disabled_checks,
    )
    return Document(
        metadata=DocumentMetadata(title="X"),
        page_sections=[
            PageSection(
                id="main",
                name="Основная",
                type="main",
                page=PageGeometry(),
                page_numbering=PageNumberingConfig(),
                content=[section],
            )
        ],
    )


def test_filter_passes_through_when_no_disabled_sections() -> None:
    doc = _make_doc_with_section([])
    violations = [
        Violation(
            check_code="T.01",
            severity="error",
            message="x",
            location="page_sections.main.content.sec-titul.paragraph",
        )
    ]
    out = _filter_disabled_section_violations(doc, violations)
    assert len(out) == 1


def test_filter_drops_violation_for_specific_code() -> None:
    doc = _make_doc_with_section(["T.01"])
    violations = [
        Violation(
            check_code="T.01",
            severity="error",
            message="x",
            location="page_sections.main.content.sec-titul.paragraph",
        ),
        Violation(
            check_code="H.01",
            severity="error",
            message="y",
            location="page_sections.main.content.sec-titul.heading",
        ),
    ]
    out = _filter_disabled_section_violations(doc, violations)
    codes = [v.check_code for v in out]
    assert codes == ["H.01"]  # T.01 ушёл, H.01 остался


def test_filter_drops_all_violations_with_wildcard() -> None:
    doc = _make_doc_with_section(["*"])
    violations = [
        Violation(
            check_code="T.01",
            severity="error",
            message="x",
            location="page_sections.main.content.sec-titul.paragraph",
        ),
        Violation(
            check_code="H.01",
            severity="error",
            message="y",
            location="page_sections.main.content.sec-titul.heading",
        ),
        Violation(
            check_code="F.01",
            severity="error",
            message="z",
            location="page_sections.main",  # не относится к sec-titul
        ),
    ]
    out = _filter_disabled_section_violations(doc, violations)
    codes = [v.check_code for v in out]
    # T.01, H.01 — внутри sec-titul, фильтруются. F.01 — глобальный, остаётся.
    assert codes == ["F.01"]


def test_filter_does_not_affect_other_sections() -> None:
    """Disabled-checks секции A не отключают проверки в секции B."""
    doc = _make_doc_with_section(["*"])
    # Добавим вторую секцию без disabled.
    doc.page_sections[0].content.append(
        LogicalSection(
            id="sec-intro",
            heading=[TextRun(text="Введение")],
            level=1,
        )
    )
    violations = [
        Violation(
            check_code="T.01",
            severity="error",
            message="x",
            location="page_sections.main.content.sec-titul.p",
        ),
        Violation(
            check_code="T.01",
            severity="error",
            message="y",
            location="page_sections.main.content.sec-intro.p",
        ),
    ]
    out = _filter_disabled_section_violations(doc, violations)
    assert len(out) == 1
    assert "sec-intro" in out[0].location


def test_filter_with_violation_without_location() -> None:
    """Violation без location не фильтруется (глобальное нарушение)."""
    doc = _make_doc_with_section(["*"])
    violations = [
        Violation(
            check_code="V.01",
            severity="error",
            message="недостаточный объём",
            location="",
        )
    ]
    out = _filter_disabled_section_violations(doc, violations)
    assert len(out) == 1


# --- Builder API ---


def test_skip_checks_adds_codes() -> None:
    b = (
        work("X", year=2026)
        .section("Титул")
        .paragraph("p")
        .skip_checks("T.01", "H.01")
    )
    doc = b.build()
    sec = doc.page_sections[0].content[0]
    assert isinstance(sec, LogicalSection)
    assert sec.disabled_checks == ["H.01", "T.01"]


def test_skip_checks_deduplicates() -> None:
    b = (
        work("X", year=2026)
        .section("Титул")
        .paragraph("p")
        .skip_checks("T.01", "T.01", "H.01")
    )
    doc = b.build()
    sec = doc.page_sections[0].content[0]
    assert sec.disabled_checks == ["H.01", "T.01"]


def test_skip_checks_multiple_calls_accumulate() -> None:
    b = (
        work("X", year=2026)
        .section("Титул")
        .paragraph("p")
        .skip_checks("T.01")
        .skip_checks("H.01")
    )
    doc = b.build()
    sec = doc.page_sections[0].content[0]
    assert sec.disabled_checks == ["H.01", "T.01"]


def test_skip_all_checks_uses_wildcard() -> None:
    b = (
        work("X", year=2026)
        .section("Титул")
        .paragraph("p")
        .skip_all_checks()
    )
    doc = b.build()
    sec = doc.page_sections[0].content[0]
    assert sec.disabled_checks == ["*"]


def test_skip_checks_does_not_affect_other_sections() -> None:
    b = (
        work("X", year=2026)
        .section("Титул")
        .paragraph("p")
        .skip_checks("T.01")
        .section("Введение")
        .paragraph("p")
    )
    doc = b.build()
    titul, intro = doc.page_sections[0].content[:2]
    assert isinstance(titul, LogicalSection)
    assert isinstance(intro, LogicalSection)
    assert titul.disabled_checks == ["T.01"]
    assert intro.disabled_checks == []


# --- Интеграционный smoke ---


def test_skip_all_checks_filters_violations_for_section() -> None:
    """Сквозной: build → validate с .skip_all_checks() — нарушения раздела
    действительно не показываются."""
    profile = load_profile("gost-7.32-2017")

    b1 = (
        work("X", year=2026)
        .section("Титульный лист")
        .paragraph("дефолт")
        .section("Введение")
        .paragraph("Актуальность.")
        .section("Список использованных источников")
        .reference("Кнут. — М., 2007.")
    )
    doc1 = b1.build()
    violations1 = validate(doc1, profile)

    b2 = (
        work("X", year=2026)
        .section("Титульный лист")
        .paragraph("дефолт")
        .skip_all_checks()
        .section("Введение")
        .paragraph("Актуальность.")
        .section("Список использованных источников")
        .reference("Кнут. — М., 2007.")
    )
    doc2 = b2.build()
    violations2 = validate(doc2, profile)

    # С skip_all_checks нарушений должно быть не больше, чем без.
    assert len(violations2) <= len(violations1)
    # И нарушений С location, указывающим на sec-1 (титульный) — ноль.
    titul_id = doc2.page_sections[0].content[0].id
    for v in violations2:
        assert titul_id not in v.location, (
            f"Violation для отключённой секции просочилось: {v.check_code} @ {v.location}"
        )


def test_skip_specific_check_filters_only_that_code() -> None:
    """skip_checks('R.10') — фильтрует только R.10 для этой секции."""
    profile = load_profile("gost-7.32-2017")

    b = (
        work("X", year=2026)
        .section("Список использованных источников")
        .reference("какой-то текст без формата")
        .skip_checks("R.10")
    )
    doc = b.build()
    violations = validate(doc, profile)
    # R.10 для bib-секции отфильтрован.
    sec_id = doc.page_sections[0].content[0].id
    r10_in_sec = [
        v for v in violations if v.check_code == "R.10" and sec_id in v.location
    ]
    assert not r10_in_sec
