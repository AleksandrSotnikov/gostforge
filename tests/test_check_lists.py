"""Тесты L.* — проверки списков (маркеры, нумерация, пунктуация)."""

# ruff: noqa: RUF001, RUF002

from gostforge.model import (
    Document,
    ListBlock,
    LogicalSection,
    PageSection,
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


# --- L.01 (маркер ненумерованного списка) -----------------------------------


def test_l01_registered() -> None:
    assert "L.01" in registered_checks()


def test_l01_allowed_marker_no_violation() -> None:
    """Маркер «-» входит в allowed_markers по умолчанию — нарушения нет."""
    lb = ListBlock(
        id="list-1",
        ordered=False,
        items=[
            [TextRun(text="- первый пункт")],
            [TextRun(text="- второй пункт")],
        ],
    )
    doc = _doc_with_content([lb])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "L.01"]
    assert found == []


def test_l01_disallowed_marker_violation() -> None:
    """Маркер «*» не входит в allowed_markers — warning."""
    lb = ListBlock(
        id="list-1",
        ordered=False,
        items=[
            [TextRun(text="* пункт со звёздочкой")],
            [TextRun(text="* ещё один")],
        ],
    )
    doc = _doc_with_content([lb])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "L.01"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["marker"] == "*"
    assert found[0].details["list_id"] == "list-1"


def test_l01_no_marker_in_text_skipped() -> None:
    """Если items[0] начинается с буквы — маркер задан стилем, проверка пропускается."""
    lb = ListBlock(
        id="list-1",
        ordered=False,
        items=[
            [TextRun(text="первый пункт без префикса")],
            [TextRun(text="второй пункт")],
        ],
    )
    doc = _doc_with_content([lb])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "L.01"]
    assert found == []


def test_l01_ordered_list_skipped() -> None:
    """Нумерованные списки L.01 не проверяет."""
    lb = ListBlock(
        id="list-1",
        ordered=True,
        items=[
            [TextRun(text="1) первый")],
            [TextRun(text="2) второй")],
        ],
    )
    doc = _doc_with_content([lb])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "L.01"]
    assert found == []


def test_l01_custom_allowed_markers_param() -> None:
    """Параметр allowed_markers переопределяет дефолт."""
    lb = ListBlock(
        id="list-1",
        ordered=False,
        items=[
            [TextRun(text="• первый")],
            [TextRun(text="• второй")],
        ],
    )
    doc = _doc_with_content([lb])
    profile = load_profile("gost-7.32-2017")
    # Запрещаем «•», оставляя только тире.
    profile.checks["L.01"].params["allowed_markers"] = ["-", "–"]
    found = [v for v in validate(doc, profile) if v.check_code == "L.01"]
    assert len(found) == 1
    assert found[0].details["marker"] == "•"


def test_l01_in_nested_section() -> None:
    """L.01 рекурсивно обходит LogicalSection."""
    lb = ListBlock(
        id="list-deep",
        ordered=False,
        items=[
            [TextRun(text="* плохой маркер")],
            [TextRun(text="* ещё пункт")],
        ],
    )
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[lb],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "L.01"]
    assert len(found) == 1
    assert found[0].details["list_id"] == "list-deep"
