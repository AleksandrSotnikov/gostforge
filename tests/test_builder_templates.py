"""Тесты шаблонов работ (coursework / bachelor_thesis / research_report)."""

from __future__ import annotations

from pathlib import Path

from gostforge.builder import WorkBuilder
from gostforge.builder.templates import (
    bachelor_thesis_template,
    coursework_template,
    research_report_template,
)
from gostforge.model import LogicalSection, TextRun
from gostforge.profile import load_profile
from gostforge.validator import validate


def _heading_text(section: LogicalSection) -> str:
    return "".join(el.text for el in section.heading if isinstance(el, TextRun))


def _top_level_headings(builder: WorkBuilder) -> list[str]:
    doc = builder.build()
    out: list[str] = []
    for ps in doc.page_sections:
        for child in ps.content:
            if isinstance(child, LogicalSection):
                out.append(_heading_text(child))
    return out


def test_coursework_template_has_required_sections() -> None:
    headings = [h.upper() for h in _top_level_headings(coursework_template("Курсовая", author="Иванов"))]
    assert "ВВЕДЕНИЕ" in headings
    assert "ЗАКЛЮЧЕНИЕ" in headings
    assert any("СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ" in h for h in headings)


def test_bachelor_thesis_template_has_two_chapters() -> None:
    builder = bachelor_thesis_template("ВКР", author="Иванов", year=2026)
    headings = [h.upper() for h in _top_level_headings(builder)]
    doc = builder.build()
    assert any("ГЛАВА 1" in h for h in headings)
    assert any("ГЛАВА 2" in h for h in headings)
    assert doc.metadata.work_type == "bachelor_thesis"


def test_research_report_template_has_referat() -> None:
    builder = research_report_template("НИР", year=2026, organization="Org")
    headings = [h.upper() for h in _top_level_headings(builder)]
    doc = builder.build()
    assert "РЕФЕРАТ" in headings
    assert "ВВЕДЕНИЕ" in headings
    assert doc.metadata.work_type == "research_report"
    assert doc.metadata.organization == "Org"


def test_template_passes_validation() -> None:
    """Документ, собранный из любого шаблона, проходит профильные проверки.

    На текущем наборе включена только F.01 (поля страницы); конструктор
    всегда выставляет валидную геометрию, так что ошибок быть не должно.
    """
    profile = load_profile("gost-7.32-2017")
    for builder in (
        coursework_template("Курсовая", author="A", year=2026),
        bachelor_thesis_template("ВКР", author="B", year=2026),
        research_report_template("НИР", year=2026),
    ):
        doc = builder.build()
        errors = [v for v in validate(doc, profile) if v.severity == "error"]
        assert errors == [], (
            f"Шаблон даёт ошибки: {[(v.check_code, v.message) for v in errors]}"
        )


def test_template_save_writes_docx(tmp_path: Path) -> None:
    """Шаблон + save() создаёт читаемый .docx."""
    out = tmp_path / "thesis.docx"
    builder = bachelor_thesis_template("ВКР", author="Иванов", year=2026)
    builder.save(out, profile="gost-7.32-2017")
    assert out.exists()
    assert out.stat().st_size > 0
