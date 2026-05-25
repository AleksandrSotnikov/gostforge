"""Тесты движка валидатора."""

from gostforge.model import Document, PageGeometry, PageSection
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def test_at_least_one_check_registered() -> None:
    assert "F.01" in registered_checks()


def test_correct_margins_no_violations() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=PageGeometry(margins_mm={"top": 20, "right": 15, "bottom": 20, "left": 30}),
        )
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "F.01"]
    assert violations == []


def test_wrong_margins_produces_violation() -> None:
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=PageGeometry(margins_mm={"top": 25, "right": 15, "bottom": 20, "left": 30}),
        )
    )
    profile = load_profile("gost-7.32-2017")
    violations = [v for v in validate(doc, profile) if v.check_code == "F.01"]
    assert len(violations) == 1
    assert violations[0].severity == "error"
    assert "top" in violations[0].location
