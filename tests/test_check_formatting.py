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


# --- F.06 -------------------------------------------------------------------


def _section_with_numbering(
    *,
    visible: bool,
    start_mode: str,
    start_value: int | None,
) -> PageSection:
    """PageSection с заданной конфигурацией нумерации."""
    return PageSection(
        id="main",
        name="Основная часть",
        type="main",
        page_numbering=PageNumberingConfig(
            visible=visible,
            start_mode=start_mode,  # type: ignore[arg-type]
            start_value=start_value,
        ),
    )


def test_f06_registered() -> None:
    assert "F.06" in registered_checks()


def test_f06_correct_start_value_no_violation() -> None:
    """start_at=3 совпадает с ожидаемым profile.params.start_value=3."""
    doc = _doc(
        _section_with_numbering(visible=True, start_mode="start_at", start_value=3)
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.06"]
    assert found == []


def test_f06_wrong_start_value_violation() -> None:
    """start_at=5 при ожидании 3 — нарушение."""
    doc = _doc(
        _section_with_numbering(visible=True, start_mode="start_at", start_value=5)
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.06"]
    assert len(found) == 1
    assert "5" in found[0].message
    assert found[0].details.get("expected") == "3"
    assert found[0].details.get("actual") == "5"


def test_f06_continue_mode_skipped() -> None:
    """start_mode=continue — мягкая семантика, проверка не применяется."""
    doc = _doc(
        _section_with_numbering(visible=True, start_mode="continue", start_value=None)
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.06"]
    assert found == []


def test_f06_invisible_numbering_skipped() -> None:
    """На титульном листе нумерация выключена — F.06 не применяется."""
    doc = _doc(
        _section_with_numbering(visible=False, start_mode="start_at", start_value=99)
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.06"]
    assert found == []


def test_f06_param_unset_skips_check() -> None:
    """Без params.start_value в профиле проверка пропускается."""
    doc = _doc(
        _section_with_numbering(visible=True, start_mode="start_at", start_value=42)
    )
    profile = load_profile("gost-7.32-2017")
    profile.checks["F.06"].params.pop("start_value", None)
    found = [v for v in validate(doc, profile) if v.check_code == "F.06"]
    assert found == []


def test_f06_profile_param_overrides_default() -> None:
    """Можно переопределить ожидаемое значение через params."""
    doc = _doc(
        _section_with_numbering(visible=True, start_mode="start_at", start_value=2)
    )
    profile = load_profile("gost-7.32-2017")
    profile.checks["F.06"].params["start_value"] = 2
    found = [v for v in validate(doc, profile) if v.check_code == "F.06"]
    assert found == []


# --- F.05 -------------------------------------------------------------------


def test_f05_registered() -> None:
    assert "F.05" in registered_checks()


def test_f05_arabic_no_violation() -> None:
    """arabic — стандарт, нет нарушения."""
    section = PageSection(
        id="main",
        name="m",
        type="main",
        page_numbering=PageNumberingConfig(visible=True, format="arabic"),
    )
    doc = _doc(section)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.05"]
    assert found == []


def test_f05_roman_violation() -> None:
    """Римская нумерация в основном тексте — нарушение."""
    section = PageSection(
        id="main",
        name="m",
        type="main",
        page_numbering=PageNumberingConfig(visible=True, format="roman"),
    )
    doc = _doc(section)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.05"]
    assert len(found) == 1
    assert found[0].details["actual"] == "roman"


def test_f05_skipped_when_numbering_invisible() -> None:
    """Титульный лист — нумерация отключена, проверку не запускаем."""
    section = PageSection(
        id="title",
        name="Титул",
        type="title",
        page_numbering=PageNumberingConfig(visible=False, format="roman"),
    )
    doc = _doc(section)
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "F.05"]
    assert found == []


def test_f05_profile_param_overrides_default() -> None:
    """Профиль может потребовать roman — тогда arabic будет нарушением."""
    section = PageSection(
        id="main",
        name="m",
        type="main",
        page_numbering=PageNumberingConfig(visible=True, format="arabic"),
    )
    doc = _doc(section)
    profile = load_profile("gost-7.32-2017")
    profile.checks["F.05"].params["format"] = "roman"
    found = [v for v in validate(doc, profile) if v.check_code == "F.05"]
    assert len(found) == 1
