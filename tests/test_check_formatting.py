"""Тесты F.* — параметры страницы. F.01 проверяется в test_validator.py."""

from gostforge.model import (
    ContentTemplate,
    Document,
    HeaderConfig,
    PageNumberingConfig,
    PageSection,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _section_with_page_field(slot: str | None) -> PageSection:
    """Секция с включённой нумерацией. Если slot задан — кладём {page} в этот слот."""
    template = ContentTemplate()
    if slot == "left":
        template.left = [TextRun(text="{page}")]
    elif slot == "center":
        template.center = [TextRun(text="{page}")]
    elif slot == "right":
        template.right = [TextRun(text="{page}")]
    return PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page_numbering=PageNumberingConfig(visible=True),
        footer=HeaderConfig(default=template),
    )


def _doc(section: PageSection) -> Document:
    doc = Document()
    doc.page_sections.append(section)
    return doc


def test_f04_registered() -> None:
    assert "F.04" in registered_checks()


def test_f04_page_field_in_correct_slot_no_violation() -> None:
    doc = _doc(_section_with_page_field("center"))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.04"]
    assert found == []


def test_f04_missing_page_field_violation() -> None:
    doc = _doc(_section_with_page_field(None))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.04"]
    assert len(found) == 1
    assert "поле PAGE" in found[0].message


def test_f04_wrong_slot_violation() -> None:
    """По умолчанию ждём bottom_center. Если {page} в right — нарушение."""
    doc = _doc(_section_with_page_field("right"))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.04"]
    assert len(found) == 1
    assert "не в ожидаемом положении" in found[0].message


def test_f04_skips_sections_without_page_numbering() -> None:
    """На титульном листе нумерация отключена — проверка не применяется."""
    section = PageSection(
        id="title",
        name="Титульный лист",
        type="title",
        page_numbering=PageNumberingConfig(visible=False),
    )
    doc = _doc(section)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.04"]
    assert found == []


def test_f04_uses_profile_position_param() -> None:
    """Если в профиле задано bottom_right — {page} в center даст нарушение."""
    doc = _doc(_section_with_page_field("center"))
    profile = load_profile("gost-7.32-2017")
    profile.checks["F.04"].params["position"] = "bottom_right"
    found = [v for v in validate(doc, profile) if v.check_code == "F.04"]
    assert len(found) == 1
