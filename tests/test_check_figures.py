"""Тесты I.01 — у каждого рисунка должна быть подпись."""

# ruff: noqa: RUF001, RUF002

from gostforge.model import (
    Document,
    Figure,
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


def test_i01_registered() -> None:
    assert "I.01" in registered_checks()


def test_i01_figure_with_caption_no_violation() -> None:
    figure = Figure(
        id="fig-1",
        image_path="",
        caption=[TextRun(text="Рисунок 1 — Схема алгоритма")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert found == []


def test_i01_figure_without_caption_violation() -> None:
    figure = Figure(id="fig-1", image_path="", caption=[])
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1
    assert found[0].details["figure_id"] == "fig-1"
    assert "fig-1" in found[0].location


def test_i01_figure_with_empty_text_caption_violation() -> None:
    """Caption из TextRun только с пробелами — тоже нарушение."""
    figure = Figure(
        id="fig-2",
        image_path="",
        caption=[TextRun(text="   ")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1


def test_i01_figures_in_logical_sections() -> None:
    """Рисунки внутри LogicalSection.children тоже проверяются."""
    fig_ok = Figure(id="fig-a", caption=[TextRun(text="Рисунок A")])
    fig_bad = Figure(id="fig-b", caption=[])
    section = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[Paragraph(id="p-1"), fig_ok, fig_bad],
    )
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1
    assert found[0].details["figure_id"] == "fig-b"


def test_i01_nested_logical_sections() -> None:
    """Рисунки во вложенных подсекциях тоже находятся."""
    fig_bad = Figure(id="fig-deep", caption=[])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[fig_bad],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.01"]
    assert len(found) == 1
    assert found[0].details["figure_id"] == "fig-deep"


# --- I.03 -------------------------------------------------------------------


def test_i03_registered() -> None:
    assert "I.03" in registered_checks()


def test_i03_correct_caption_no_violation() -> None:
    """«Рисунок 1 — Название» — корректная подпись."""
    figure = Figure(
        id="fig-1",
        caption=[TextRun(text="Рисунок 1 — Схема алгоритма")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert found == []


def test_i03_dot_after_number_violation() -> None:
    """«Рисунок 1. Название» — нарушение (нужно длинное тире)."""
    figure = Figure(
        id="fig-1",
        caption=[TextRun(text="Рисунок 1. Схема алгоритма")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert len(found) == 1
    assert "не соответствует формату" in found[0].message


def test_i03_hyphen_instead_of_em_dash_allowed_softly() -> None:
    """ASCII-дефис ‘-’ принимается (regex допускает [—–-])."""
    figure = Figure(
        id="fig-1",
        caption=[TextRun(text="Рисунок 1 - Схема алгоритма")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert found == []


def test_i03_no_number_violation() -> None:
    """«Рисунок Схема» — без номера — нарушение."""
    figure = Figure(id="fig-1", caption=[TextRun(text="Рисунок Схема алгоритма")])
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert len(found) == 1


def test_i03_multilevel_number_ok() -> None:
    """«Рисунок 1.2 — Название» — корректно."""
    figure = Figure(
        id="fig-1",
        caption=[TextRun(text="Рисунок 1.2 — Анализ")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert found == []


def test_i03_empty_caption_not_flagged() -> None:
    """Пустая подпись — это случай I.01, не дублируем."""
    figure = Figure(id="fig-1", caption=[])
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert found == []


def test_i03_allow_dot_after_number_param() -> None:
    """С allow_dot_after_number=True «Рисунок 1. Схема» — не нарушение."""
    figure = Figure(
        id="fig-1",
        caption=[TextRun(text="Рисунок 1. Схема алгоритма")],
    )
    doc = _doc_with_content([figure])
    profile = load_profile("gost-7.32-2017")
    profile.checks["I.03"].params["allow_dot_after_number"] = True
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert found == []


def test_i03_caption_in_nested_section() -> None:
    """I.03 рекурсивно обходит LogicalSection."""
    fig_bad = Figure(id="fig-deep", caption=[TextRun(text="Рисунок 1. Bad")])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[fig_bad],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.03"]
    assert len(found) == 1
    assert found[0].details["figure_id"] == "fig-deep"


# --- I.05 (сквозная нумерация рисунков) ---------------------------------


def test_i05_registered() -> None:
    assert "I.05" in registered_checks()


def test_i05_continuous_numbering_no_violation() -> None:
    """Рисунки 1, 2, 3 — нарушения нет."""
    figs = [
        Figure(id=f"f-{i}", caption=[TextRun(text=f"Рисунок {i} — Имя {i}")])
        for i in (1, 2, 3)
    ]
    doc = _doc_with_content(list(figs))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.05"]
    assert found == []


def test_i05_gap_in_numbering_violation() -> None:
    """Рисунки 1, 3 — пропуск второго номера."""
    figs = [
        Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — A")]),
        Figure(id="f-3", caption=[TextRun(text="Рисунок 3 — C")]),
    ]
    doc = _doc_with_content(list(figs))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.05"]
    assert len(found) == 1
    assert found[0].details["expected"] == "2"
    assert found[0].details["found"] == "3"


def test_i05_duplicate_number_violation() -> None:
    """Два рисунка с номером 1 — нарушение «дубликат»."""
    figs = [
        Figure(id="f-a", caption=[TextRun(text="Рисунок 1 — A")]),
        Figure(id="f-b", caption=[TextRun(text="Рисунок 1 — B")]),
    ]
    doc = _doc_with_content(list(figs))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.05"]
    assert len(found) == 1
    assert "встречается у двух" in found[0].message
    assert found[0].details["duplicate_of"] == "f-a"


def test_i05_starts_not_from_one_violation() -> None:
    """Первый рисунок — 2, должно быть 1."""
    figs = [
        Figure(id="f-2", caption=[TextRun(text="Рисунок 2 — B")]),
        Figure(id="f-3", caption=[TextRun(text="Рисунок 3 — C")]),
    ]
    doc = _doc_with_content(list(figs))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.05"]
    assert any(v.details.get("expected") == "1" for v in found)


def test_i05_empty_caption_skipped() -> None:
    """Пустые подписи — это случай I.01, не учитываются в I.05."""
    figs = [
        Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — A")]),
        Figure(id="f-2", caption=[]),  # пустая, не считается
        Figure(id="f-2b", caption=[TextRun(text="Рисунок 2 — B")]),
    ]
    doc = _doc_with_content(list(figs))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.05"]
    assert found == []


def test_i05_nested_logical_sections() -> None:
    """Рисунки во вложенных секциях тоже участвуют в сквозной нумерации."""
    fig1 = Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — A")])
    fig3 = Figure(id="f-3", caption=[TextRun(text="Рисунок 3 — C")])
    inner = LogicalSection(
        id="sec-2", level=2, heading=[TextRun(text="Sub")], children=[fig3]
    )
    outer = LogicalSection(
        id="sec-1", level=1, heading=[TextRun(text="Main")], children=[fig1, inner]
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.05"]
    assert len(found) == 1
    assert found[0].details["found"] == "3"


def test_i05_no_figures_no_violation() -> None:
    """Документ без рисунков — нет нарушений."""
    doc = _doc_with_content([])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "I.05"]
    assert found == []
