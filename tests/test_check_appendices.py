"""Тесты P.01 — маркировка приложений без запрещённых букв."""

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
        id="appendix",
        name="app",
        type="appendix",
        content=list(items),  # type: ignore[arg-type]
    )
    doc.page_sections.append(page_section)
    return doc


def _appendix(section_id: str, title: str) -> LogicalSection:
    """Удобный конструктор приложения уровня 1 с заданным заголовком."""
    return LogicalSection(
        id=section_id,
        level=1,
        heading=[TextRun(text=title)],
        children=[Paragraph(id=f"p-{section_id}", content=[TextRun(text="...")])],
    )


def test_p01_registered() -> None:
    assert "P.01" in registered_checks()


def test_p01_correct_sequence_no_violation() -> None:
    """Приложение А, Б, В — корректная последовательность, нет нарушений."""
    sections = [
        _appendix("app-a", "Приложение А"),
        _appendix("app-b", "Приложение Б"),
        _appendix("app-c", "Приложение В"),
    ]
    doc = _doc_with_content(list(sections))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert found == []


def test_p01_forbidden_letter_violation() -> None:
    """Приложение Ё — запрещённая буква, нарушение."""
    sections = [
        _appendix("app-a", "Приложение А"),
        _appendix("app-yo", "Приложение Ё"),
    ]
    doc = _doc_with_content(list(sections))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert any(v.details.get("letter") == "Ё" and "запрещённая" in v.message for v in found)


def test_p01_gap_in_sequence_violation() -> None:
    """Приложение А → В (пропуск Б) — нарушение порядка."""
    sections = [
        _appendix("app-a", "Приложение А"),
        _appendix("app-c", "Приложение В"),
    ]
    doc = _doc_with_content(list(sections))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert found[0].details["expected"] == "Б"
    assert found[0].details["found"] == "В"


def test_p01_latin_letter_violation() -> None:
    """Приложение A (латинская) — нарушение «латинская буква»."""
    section = _appendix("app-a", "Приложение A")
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert "латинской" in found[0].message


def test_p01_lowercase_letter_violation() -> None:
    """Приложение а (строчная) — нарушение «строчная»."""
    section = _appendix("app-a", "Приложение а")
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert "строчной" in found[0].message


def test_p01_not_starting_from_a_violation() -> None:
    """Первое приложение — Б — нарушение (должно начинаться с А)."""
    section = _appendix("app-b", "Приложение Б")
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert len(found) == 1
    assert found[0].details["expected"] == "А"


def test_p01_no_appendices_no_violation() -> None:
    """Документ без приложений — никаких нарушений P.01."""
    doc = _doc_with_content([])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.01"]
    assert found == []


# --- P.02 -----------------------------------------------------------------


def _doc_main_and_appendix(
    main_paragraphs: list[Paragraph],
    appendices: list[LogicalSection],
) -> Document:
    """Документ с двумя PageSection: main с параграфами и appendix с разделами."""
    doc = Document()
    main = PageSection(
        id="main",
        name="main",
        type="main",
        content=list(main_paragraphs),  # type: ignore[arg-type]
    )
    app = PageSection(
        id="app",
        name="app",
        type="appendix",
        content=list(appendices),  # type: ignore[arg-type]
    )
    doc.page_sections.append(main)
    doc.page_sections.append(app)
    return doc


def test_p02_registered() -> None:
    assert "P.02" in registered_checks()


def test_p02_reference_present_no_violation() -> None:
    """Приложение А имеет ссылку «см. приложение А» — нет нарушения."""
    main_para = Paragraph(
        id="p-1",
        content=[TextRun(text="Подробности см. приложение А.")],
    )
    app = _appendix("app-a", "Приложение А")
    doc = _doc_main_and_appendix([main_para], [app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.02"]
    assert found == []


def test_p02_no_reference_violation() -> None:
    """Приложение Б — ни одной ссылки в тексте — нарушение."""
    main_para = Paragraph(
        id="p-1",
        content=[TextRun(text="Обычный текст работы без ссылок.")],
    )
    app_a = _appendix("app-a", "Приложение А")
    app_b = _appendix("app-b", "Приложение Б")
    doc = _doc_main_and_appendix([main_para], [app_a, app_b])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.02"]
    letters = {v.details["letter"] for v in found}
    assert "А" in letters and "Б" in letters


def test_p02_alternative_reference_forms() -> None:
    """Различные формы ссылок (прил., в приложении, (приложение X)) — ок."""
    main_para_1 = Paragraph(
        id="p-1",
        content=[TextRun(text="В приложении А приведена схема.")],
    )
    main_para_2 = Paragraph(
        id="p-2",
        content=[TextRun(text="См. прил. Б для подробностей.")],
    )
    main_para_3 = Paragraph(
        id="p-3",
        content=[TextRun(text="Данные приведены (приложение В).")],
    )
    app_a = _appendix("app-a", "Приложение А")
    app_b = _appendix("app-b", "Приложение Б")
    app_c = _appendix("app-c", "Приложение В")
    doc = _doc_main_and_appendix(
        [main_para_1, main_para_2, main_para_3],
        [app_a, app_b, app_c],
    )
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.02"]
    assert found == []


# --- P.03 -----------------------------------------------------------------


def test_p03_registered() -> None:
    assert "P.03" in registered_checks()


def test_p03_page_break_true_no_violation() -> None:
    """Первый Paragraph приложения с page_break_before=True — нет нарушения."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Содержимое приложения.")],
        page_break_before=True,
    )
    app = LogicalSection(
        id="app-a",
        level=1,
        heading=[TextRun(text="Приложение А")],
        children=[para],
    )
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.03"]
    assert found == []


def test_p03_page_break_false_violation() -> None:
    """Первый Paragraph приложения с page_break_before=False — нарушение."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Содержимое приложения.")],
        page_break_before=False,
    )
    app = LogicalSection(
        id="app-a",
        level=1,
        heading=[TextRun(text="Приложение А")],
        children=[para],
    )
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.03"]
    assert len(found) == 1
    assert found[0].details["section_id"] == "app-a"


def test_p03_page_break_none_no_violation() -> None:
    """page_break_before=None (наследуется) — без нарушения."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Содержимое приложения.")],
        page_break_before=None,
    )
    app = LogicalSection(
        id="app-a",
        level=1,
        heading=[TextRun(text="Приложение А")],
        children=[para],
    )
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.03"]
    assert found == []


# --- P.04 -----------------------------------------------------------------


def test_p04_registered() -> None:
    assert "P.04" in registered_checks()


def test_p04_valid_format_no_violation() -> None:
    """«Приложение А» — корректный формат, нет нарушения."""
    app = _appendix("app-a", "Приложение А")
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.04"]
    assert found == []


def test_p04_valid_with_subtitle_no_violation() -> None:
    """«Приложение А ПРИМЕР МЕТОДИКИ» — формат с подзаголовком — ок."""
    app = LogicalSection(
        id="app-a",
        level=1,
        heading=[TextRun(text="Приложение А ПРИМЕР МЕТОДИКИ РАСЧЁТА")],
        children=[Paragraph(id="p-1", content=[TextRun(text="...")])],
    )
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.04"]
    assert found == []


def test_p04_lowercase_format_violation() -> None:
    """«Приложение а» (строчная) — нарушение формата."""
    app = _appendix("app-a", "Приложение а")
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.04"]
    assert len(found) == 1


# --- P.05 -----------------------------------------------------------------


def test_p05_registered() -> None:
    assert "P.05" in registered_checks()


def test_p05_heading_style_no_violation() -> None:
    """Первый параграф приложения в стиле Heading 2 — нет нарушения."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="ПРИМЕР МЕТОДИКИ РАСЧЁТА")],
        style_name="Heading 2",
    )
    app = LogicalSection(
        id="app-a",
        level=1,
        heading=[TextRun(text="Приложение А")],
        children=[para, Paragraph(id="p-2", content=[TextRun(text="...")])],
    )
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.05"]
    assert found == []


def test_p05_bold_no_violation() -> None:
    """Первый параграф с bold-runом — нет нарушения."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="ПРИМЕР МЕТОДИКИ", bold=True)],
    )
    app = LogicalSection(
        id="app-a",
        level=1,
        heading=[TextRun(text="Приложение А")],
        children=[para, Paragraph(id="p-2", content=[TextRun(text="...")])],
    )
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.05"]
    assert found == []


def test_p05_plain_paragraph_violation() -> None:
    """Первый параграф приложения — обычный (не bold, не Heading) — нарушение."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="обычный текст")],
    )
    app = LogicalSection(
        id="app-a",
        level=1,
        heading=[TextRun(text="Приложение А")],
        children=[para],
    )
    doc = _doc_with_content([app])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "P.05"]
    assert len(found) == 1
    assert found[0].details["section_id"] == "app-a"
