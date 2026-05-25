"""Тесты M.01 / M.03 / M.04 — нумерация и ссылки на формулы."""

# ruff: noqa: RUF001, RUF002

from gostforge.model import (
    Document,
    Formula,
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


# --- M.01 (наличие номера) ---------------------------------------------------


def test_m01_registered() -> None:
    assert "M.01" in registered_checks()


def test_m01_formula_with_number_no_violation() -> None:
    """Формула с number=1 — нарушения нет (M.01 ничего не сообщает)."""
    formula = Formula(id="formula-1", latex="E=mc^2", number=1)
    doc = _doc_with_content([formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.01"]
    assert found == []


def test_m01_formula_without_number_warning_by_default() -> None:
    """Без параметра required формула без номера даёт warning."""
    formula = Formula(id="formula-1", latex="a+b", number=None)
    doc = _doc_with_content([formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.01"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["formula_id"] == "formula-1"


def test_m01_required_true_makes_error() -> None:
    """При required=True отсутствие номера — error."""
    formula = Formula(id="formula-1", latex="a+b", number=None)
    doc = _doc_with_content([formula])
    profile = load_profile("gost-7.32-2017")
    profile.checks["M.01"].params["required"] = True
    found = [v for v in validate(doc, profile) if v.check_code == "M.01"]
    assert len(found) == 1
    assert found[0].severity == "error"


def test_m01_empty_latex_skipped() -> None:
    """Формула с пустым latex пропускается (вырожденный случай)."""
    formula = Formula(id="formula-1", latex="   ", number=None)
    doc = _doc_with_content([formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.01"]
    assert found == []


def test_m01_in_nested_section() -> None:
    """M.01 рекурсивно обходит LogicalSection."""
    formula = Formula(id="formula-deep", latex="x+y", number=None)
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[formula],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.01"]
    assert len(found) == 1
    assert found[0].details["formula_id"] == "formula-deep"


# --- M.03 (сквозная нумерация) -----------------------------------------------


def test_m03_registered() -> None:
    assert "M.03" in registered_checks()


def test_m03_continuous_numbering_no_violation() -> None:
    """Формулы 1, 2, 3 — нарушения нет."""
    formulas = [
        Formula(id=f"f-{i}", latex=f"x_{i}", number=i) for i in (1, 2, 3)
    ]
    doc = _doc_with_content(list(formulas))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.03"]
    assert found == []


def test_m03_gap_in_numbering_violation() -> None:
    """Формулы 1, 3 — пропуск второго номера."""
    formulas = [
        Formula(id="f-1", latex="a", number=1),
        Formula(id="f-3", latex="c", number=3),
    ]
    doc = _doc_with_content(list(formulas))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.03"]
    assert len(found) == 1
    assert found[0].details["expected"] == "2"
    assert found[0].details["found"] == "3"


def test_m03_duplicate_number_violation() -> None:
    """Две формулы с номером 1 — нарушение «дубликат»."""
    formulas = [
        Formula(id="f-a", latex="a", number=1),
        Formula(id="f-b", latex="b", number=1),
    ]
    doc = _doc_with_content(list(formulas))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.03"]
    assert len(found) == 1
    assert "встречается у двух" in found[0].message
    assert found[0].details["duplicate_of"] == "f-a"


def test_m03_unnumbered_formulas_skipped() -> None:
    """Формулы с number=None в M.03 не участвуют."""
    formulas = [
        Formula(id="f-1", latex="a", number=1),
        Formula(id="f-x", latex="x", number=None),
        Formula(id="f-2", latex="b", number=2),
    ]
    doc = _doc_with_content(list(formulas))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.03"]
    assert found == []


def test_m03_no_formulas_no_violation() -> None:
    """Документ без формул — нет нарушений."""
    doc = _doc_with_content([])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.03"]
    assert found == []


# --- M.04 (ссылка в тексте) --------------------------------------------------


def test_m04_registered() -> None:
    assert "M.04" in registered_checks()


def test_m04_reference_in_text_no_violation() -> None:
    """В тексте есть «(1)» — нарушения нет."""
    formula = Formula(id="f-1", latex="E=mc^2", number=1)
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Из закона сохранения (1) следует, что ...")],
    )
    doc = _doc_with_content([para, formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.04"]
    assert found == []


def test_m04_no_reference_violation() -> None:
    """Формула есть, ссылки в тексте нет — warning."""
    formula = Formula(id="f-1", latex="E=mc^2", number=1)
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Просто абзац без ссылок.")],
    )
    doc = _doc_with_content([para, formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.04"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["formula_id"] == "f-1"
    assert found[0].details["number"] == "1"


def test_m04_word_form_reference() -> None:
    """«по формуле 2» — тоже валидная ссылка."""
    formula = Formula(id="f-2", latex="x+y", number=2)
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Вычислим по формуле 2 значение.")],
    )
    doc = _doc_with_content([para, formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.04"]
    assert found == []


def test_m04_unnumbered_formula_skipped() -> None:
    """Ненумерованные формулы не требуют ссылок."""
    formula = Formula(id="f-1", latex="a+b", number=None)
    para = Paragraph(id="p-1", content=[TextRun(text="Нет ссылок.")])
    doc = _doc_with_content([para, formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.04"]
    assert found == []


# --- M.02 (пояснения переменных после формулы) -----------------------------


def test_m02_registered() -> None:
    assert "M.02" in registered_checks()


def test_m02_explanation_present_no_violation() -> None:
    """Параграф «где: a — длина...» сразу после формулы — нарушения нет."""
    formula = Formula(id="f-1", latex="a+b", number=1)
    explain = Paragraph(
        id="p-1",
        content=[TextRun(text="где: a — длина, b — ширина.")],
    )
    doc = _doc_with_content([formula, explain])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.02"]
    assert found == []


def test_m02_no_explanation_violation() -> None:
    """После формулы идёт обычный текст — Violation."""
    formula = Formula(id="f-1", latex="a+b", number=1)
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Далее рассмотрим следующий пример.")],
    )
    doc = _doc_with_content([formula, para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.02"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["formula_id"] == "f-1"


def test_m02_explanation_within_lookahead_window() -> None:
    """Параграф «здесь...» через 2 блока после формулы — нарушения нет (look_ahead=3)."""
    formula = Formula(id="f-1", latex="a+b", number=1)
    p_after = Paragraph(id="p-x", content=[TextRun(text="Расшифровка ниже.")])
    explain = Paragraph(
        id="p-1",
        content=[TextRun(text="здесь a — длина, b — ширина.")],
    )
    doc = _doc_with_content([formula, p_after, explain])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.02"]
    assert found == []


def test_m02_unnumbered_formula_skipped() -> None:
    """Ненумерованные формулы не требуют пояснения переменных."""
    formula = Formula(id="f-1", latex="a+b", number=None)
    para = Paragraph(id="p-1", content=[TextRun(text="Обычный абзац.")])
    doc = _doc_with_content([formula, para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "M.02"]
    assert found == []


# --- M.05 (формула выровнена по центру — заглушка Фазы 2) ------------------


def test_m05_registered() -> None:
    """M.05 зарегистрирована в реестре, но на Фазе 1 это заглушка."""
    assert "M.05" in registered_checks()
