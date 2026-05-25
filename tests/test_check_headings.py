# ruff: noqa: RUF002

"""Тесты H.01 и H.03 — формат заголовков."""

from gostforge.model import (
    Document,
    LogicalSection,
    PageSection,
    TextRun,
)
from gostforge.profile import load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


def _doc(sections: list[LogicalSection]) -> Document:
    doc = Document()
    doc.page_sections.append(
        PageSection(id="main", name="m", type="main", content=list(sections))
    )
    return doc


def _heading(
    text: str,
    *,
    level: int = 1,
    font: str | None = None,
    size_pt: float | None = None,
    bold: bool | None = None,
) -> LogicalSection:
    run_kwargs = {}
    if font is not None:
        run_kwargs["font"] = font
    if size_pt is not None:
        run_kwargs["size_pt"] = size_pt
    if bold is not None:
        run_kwargs["bold"] = bold
    return LogicalSection(
        id=f"sec-{text[:10]}",
        level=level,
        heading=[TextRun(text=text, **run_kwargs)],
    )


# --- H.01 -------------------------------------------------------------------


def test_h01_registered() -> None:
    assert "H.01" in registered_checks()


def test_h01_correct_heading_no_violation() -> None:
    doc = _doc(
        [_heading("ВВЕДЕНИЕ", font="Times New Roman", size_pt=14, bold=True)]
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert found == []


def test_h01_lowercase_heading_violation() -> None:
    """Профиль требует uppercase=true для heading_1."""
    doc = _doc([_heading("Введение", font="Times New Roman", size_pt=14, bold=True)])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert any("верхнем регистре" in v.message for v in found)


def test_h01_wrong_font_violation() -> None:
    doc = _doc([_heading("ВВЕДЕНИЕ", font="Arial", size_pt=14, bold=True)])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert any("Arial" in v.message for v in found)


def test_h01_not_bold_violation() -> None:
    doc = _doc([_heading("ВВЕДЕНИЕ", font="Times New Roman", size_pt=14, bold=False)])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert any("полужирным" in v.message for v in found)


def test_h01_skips_lower_level_headings() -> None:
    """H.01 — только для level=1; для level=2 свои правила (heading_2)."""
    doc = _doc([_heading("Подраздел", level=2, font="Arial", size_pt=14, bold=True)])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert found == []


def test_h01_unset_props_are_not_violations() -> None:
    """Если у TextRun font/size/bold не заданы — нарушения нет (наследуется)."""
    doc = _doc([_heading("ВВЕДЕНИЕ")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.01"]
    assert found == []


# --- H.03 -------------------------------------------------------------------


def test_h03_registered() -> None:
    assert "H.03" in registered_checks()


def test_h03_no_dot_after_number_no_violation() -> None:
    doc = _doc([_heading("1 Введение"), _heading("1.2 Анализ", level=2)])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.03"]
    assert found == []


def test_h03_dot_after_single_number_violation() -> None:
    doc = _doc([_heading("1. Введение")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.03"]
    assert len(found) == 1
    assert found[0].details["number"] == "1"


def test_h03_dot_after_multilevel_number_violation() -> None:
    doc = _doc([_heading("1.2.3. Метод", level=3)])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.03"]
    assert len(found) == 1
    assert found[0].details["number"] == "1.2.3"


def test_h03_heading_without_number_no_violation() -> None:
    doc = _doc([_heading("Введение"), _heading("Заключение")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.03"]
    assert found == []


def test_h03_traverses_nested_sections() -> None:
    inner = _heading("1.1. Подраздел", level=2)
    outer = LogicalSection(
        id="outer",
        level=1,
        heading=[TextRun(text="1 Основная часть")],
        children=[inner],
    )
    doc = _doc([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.03"]
    assert len(found) == 1
    assert "1.1" in found[0].details["number"]


# --- H.08 (заголовок не оканчивается точкой) ------------------------------


def test_h08_registered() -> None:
    assert "H.08" in registered_checks()


def test_h08_correct_heading_no_violation() -> None:
    doc = _doc([_heading("Введение"), _heading("Заключение")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.08"]
    assert found == []


def test_h08_heading_ends_with_dot_violation() -> None:
    doc = _doc([_heading("Введение.")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.08"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert "точкой" in found[0].message


def test_h08_heading_ends_with_three_dots_violation() -> None:
    """Три ASCII-точки в конце — тоже нарушение."""
    doc = _doc([_heading("Анализ предметной области...")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.08"]
    assert len(found) == 1


def test_h08_heading_ends_with_ellipsis_unicode_violation() -> None:
    """Unicode-многоточие (U+2026) — тоже нарушение."""
    doc = _doc([_heading("Анализ предметной области…")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.08"]
    assert len(found) == 1


def test_h08_heading_ends_with_question_mark_no_violation() -> None:
    """Вопросительный знак в конце — допустимо по ГОСТ Р 2.105-2019."""
    doc = _doc([_heading("Что такое нормоконтроль?")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.08"]
    assert found == []


def test_h08_heading_ends_with_colon_no_violation() -> None:
    doc = _doc([_heading("Список таблиц:")])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.08"]
    assert found == []


def test_h08_traverses_nested_sections() -> None:
    inner = _heading("Подраздел.", level=2)
    outer = LogicalSection(
        id="outer",
        level=1,
        heading=[TextRun(text="1 Основная часть")],
        children=[inner],
    )
    doc = _doc([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "H.08"]
    assert len(found) == 1
    assert "Подраздел." in found[0].message
