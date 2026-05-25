"""Тесты C.* — проверки разрешения перекрёстных ссылок.

C.01 — ссылки на рисунки указывают на существующий рисунок.
C.02 — ссылки на таблицы указывают на существующую таблицу.
C.04 — ссылки [N] разрешаются в bibliography.
"""

# ruff: noqa: RUF001, RUF002, RUF003

from gostforge.model import (
    BibliographyEntry,
    Document,
    Figure,
    Formula,
    LogicalSection,
    PageSection,
    Paragraph,
    Table,
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


# --- C.01 -------------------------------------------------------------------


def test_c01_registered() -> None:
    assert "C.01" in registered_checks()


def test_c01_reference_resolves_no_violation() -> None:
    """Ссылка «см. рисунок 1» при наличии рисунка 1 — нет нарушения."""
    figure = Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — Схема")])
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Алгоритм представлен на рисунке 1.")],
    )
    doc = _doc_with_content([para, figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.01"]
    assert found == []


def test_c01_reference_to_missing_figure_violation() -> None:
    """Ссылка «см. рисунок 5» при отсутствии рисунка 5 — нарушение."""
    figure = Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — Схема")])
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. рисунок 5 для деталей.")],
    )
    doc = _doc_with_content([para, figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.01"]
    assert len(found) == 1
    assert found[0].details["number"] == "5"
    assert found[0].details["paragraph_id"] == "p-1"


def test_c01_reference_in_figure_caption_not_counted() -> None:
    """Ссылка «Рисунок 5» в caption самого рисунка не считается ссылкой.

    C.01 проходит только по Paragraph'ам; Figure.caption — это
    `list[InlineElement]`, не Paragraph, поэтому регрессий не должно быть.
    """
    # Рисунок 1 существует; caption содержит «Рисунок 5» (как часть подписи).
    figure = Figure(
        id="f-1",
        caption=[TextRun(text="Рисунок 5 — Хитрая подпись с большим номером")],
    )
    # В тексте — никаких ссылок на несуществующие рисунки.
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Просто абзац без ссылок.")],
    )
    doc = _doc_with_content([para, figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.01"]
    assert found == []


def test_c01_abbreviated_form_resolves() -> None:
    """«рис. 1» — корректная разрешаемая ссылка."""
    figure = Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — Схема")])
    para = Paragraph(id="p-1", content=[TextRun(text="См. рис. 1.")])
    doc = _doc_with_content([para, figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.01"]
    assert found == []


def test_c01_multiple_references_some_unresolved() -> None:
    """Из двух ссылок одна указывает в пустоту — одно нарушение."""
    figure = Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — Схема")])
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. рисунок 1 и рисунок 7.")],
    )
    doc = _doc_with_content([para, figure])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.01"]
    assert len(found) == 1
    assert found[0].details["number"] == "7"


def test_c01_reference_inside_nested_section() -> None:
    """Ссылка в параграфе внутри вложенной секции тоже проверяется."""
    figure = Figure(id="f-1", caption=[TextRun(text="Рисунок 1 — Схема")])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[Paragraph(id="p-1", content=[TextRun(text="См. рисунок 42.")])],
    )
    doc = _doc_with_content([figure, inner])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.01"]
    assert len(found) == 1
    assert found[0].details["number"] == "42"


# --- C.02 -------------------------------------------------------------------


def test_c02_registered() -> None:
    assert "C.02" in registered_checks()


def test_c02_reference_resolves_no_violation() -> None:
    """Ссылка «см. таблицу 1» при наличии таблицы 1 — нет нарушения."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Сводка")])
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Данные представлены в таблице 1.")],
    )
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.02"]
    assert found == []


def test_c02_reference_to_missing_table_violation() -> None:
    """Ссылка «см. таблицу 3» при отсутствии таблицы 3 — нарушение."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Сводка")])
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. таблицу 3 для деталей.")],
    )
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.02"]
    assert len(found) == 1
    assert found[0].details["number"] == "3"


def test_c02_reference_in_table_caption_not_counted() -> None:
    """Ссылка «Таблица 5» в caption самой таблицы не считается ссылкой.

    C.02 проходит только по Paragraph'ам; Table.caption — это
    `list[InlineElement]`, не Paragraph.
    """
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 5 — Хитрая подпись с большим номером")],
    )
    # В тексте — никаких ссылок на несуществующие таблицы.
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Просто абзац без ссылок.")],
    )
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.02"]
    assert found == []


def test_c02_abbreviated_form_resolves() -> None:
    """«табл. 1» — корректная разрешаемая ссылка."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Сводка")])
    para = Paragraph(id="p-1", content=[TextRun(text="См. табл. 1.")])
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.02"]
    assert found == []


def test_c02_multiple_references_some_unresolved() -> None:
    """Из двух ссылок одна указывает в пустоту — одно нарушение."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Сводка")])
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. таблицу 1 и таблицу 9.")],
    )
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.02"]
    assert len(found) == 1
    assert found[0].details["number"] == "9"


# --- C.04 -------------------------------------------------------------------


def _doc_with_bibliography_and_paragraphs(
    bib_count: int,
    paragraphs: list[Paragraph],
) -> Document:
    """Сделать Document с bib_count записями и заданным набором параграфов."""
    doc = Document()
    for i in range(1, bib_count + 1):
        doc.bibliography.append(
            BibliographyEntry(id=f"ref-{i}", type="book", fields={"title": f"T{i}"})
        )
    page_section = PageSection(
        id="main",
        name="m",
        type="main",
        content=list(paragraphs),  # type: ignore[arg-type]
    )
    doc.page_sections.append(page_section)
    return doc


def test_c04_registered() -> None:
    assert "C.04" in registered_checks()


def test_c04_reference_resolves_no_violation() -> None:
    """[1] при наличии одной записи в bibliography — нарушения нет."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Как показано в [1], алгоритм эффективен.")],
    )
    doc = _doc_with_bibliography_and_paragraphs(1, [para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.04"]
    assert found == []


def test_c04_dangling_reference_violation() -> None:
    """[5] при наличии только 2 записей — нарушение."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. [5] для деталей.")],
    )
    doc = _doc_with_bibliography_and_paragraphs(2, [para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.04"]
    assert len(found) == 1
    assert found[0].details["number"] == "5"
    assert found[0].details["bibliography_size"] == "2"


def test_c04_range_partially_resolves() -> None:
    """[1-3] при наличии 2 записей: 1, 2 — ок, 3 — нарушение."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. работы [1-3] по теме.")],
    )
    doc = _doc_with_bibliography_and_paragraphs(2, [para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.04"]
    assert len(found) == 1
    assert found[0].details["number"] == "3"


def test_c04_compound_reference_some_unresolved() -> None:
    """[1, 5, 7] при 3 записях: 5 и 7 — нарушения."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. [1, 5, 7] по теме.")],
    )
    doc = _doc_with_bibliography_and_paragraphs(3, [para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.04"]
    numbers = sorted(int(v.details["number"]) for v in found)
    assert numbers == [5, 7]


def test_c04_empty_bibliography_all_references_violate() -> None:
    """Пустой bibliography — каждая ссылка [N] нарушает."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="См. [1] и [2].")],
    )
    doc = _doc_with_bibliography_and_paragraphs(0, [para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.04"]
    assert len(found) == 2
    numbers = sorted(int(v.details["number"]) for v in found)
    assert numbers == [1, 2]


def test_c04_no_references_no_violation() -> None:
    """В тексте нет [N] — нет нарушений, даже при пустом bibliography."""
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Обычный текст без библиографических ссылок.")],
    )
    doc = _doc_with_bibliography_and_paragraphs(0, [para])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.04"]
    assert found == []


# --- C.03 -------------------------------------------------------------------


def test_c03_registered() -> None:
    assert "C.03" in registered_checks()


def test_c03_reference_resolves_no_violation() -> None:
    """Ссылка «формула 1» при наличии Formula(number=1) — нет нарушения."""
    formula = Formula(id="f-1", latex="x = 1", number=1)
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="По формуле 1 получаем значение.")],
    )
    doc = _doc_with_content([para, formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.03"]
    assert found == []


def test_c03_reference_to_missing_formula_violation() -> None:
    """Ссылка «формуле 5» при отсутствии Formula(number=5) — нарушение."""
    formula = Formula(id="f-1", latex="x = 1", number=1)
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="По формуле 5 получаем значение.")],
    )
    doc = _doc_with_content([para, formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.03"]
    assert len(found) == 1
    assert found[0].details["number"] == "5"


def test_c03_paren_reference_violation() -> None:
    """«(7)» при наличии формулы 1 — нарушение (формулы 7 нет)."""
    formula = Formula(id="f-1", latex="x = 1", number=1)
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Из выражения (7) следует результат.")],
    )
    doc = _doc_with_content([para, formula])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "C.03"]
    numbers = {v.details["number"] for v in found}
    assert "7" in numbers


