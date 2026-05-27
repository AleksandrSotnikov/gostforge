"""Тесты B.01 — у каждой таблицы должна быть подпись."""

from gostforge.model import (
    Document,
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


def test_b01_registered() -> None:
    assert "B.01" in registered_checks()


def test_b01_table_with_caption_no_violation() -> None:
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — Результаты")],
        headers=[[TextRun(text="A")]],
        rows=[[[TextRun(text="1")]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert found == []


def test_b01_table_without_caption_violation() -> None:
    table = Table(
        id="t-1",
        caption=[],
        headers=[[TextRun(text="A")]],
        rows=[[[TextRun(text="1")]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-1"
    assert "t-1" in found[0].location


def test_b01_table_with_empty_text_caption_violation() -> None:
    """Caption из TextRun только с пробелами — тоже нарушение."""
    table = Table(id="t-2", caption=[TextRun(text=" ")])
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1


def test_b01_tables_in_logical_sections() -> None:
    """Таблицы внутри LogicalSection.children тоже проверяются."""
    table_ok = Table(id="t-a", caption=[TextRun(text="Таблица A")])
    table_bad = Table(id="t-b", caption=[])
    section = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[Paragraph(id="p-1"), table_ok, table_bad],
    )
    doc = _doc_with_content([section])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-b"


def test_b01_nested_logical_sections() -> None:
    """Таблицы во вложенных подсекциях тоже находятся."""
    table_bad = Table(id="t-deep", caption=[])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[table_bad],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.01"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-deep"


# --- B.03 -------------------------------------------------------------------


def test_b03_registered() -> None:
    assert "B.03" in registered_checks()


def test_b03_correct_caption_no_violation() -> None:
    """«Таблица 1 — Название» — корректная подпись."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — Результаты")],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert found == []


def test_b03_dot_after_number_violation() -> None:
    """«Таблица 1. Название» — нарушение."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1. Результаты")],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert len(found) == 1
    assert "не соответствует формату" in found[0].message


def test_b03_hyphen_accepted() -> None:
    """ASCII-дефис ‘-’ принимается."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 - Результаты")],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert found == []


def test_b03_no_number_violation() -> None:
    table = Table(id="t-1", caption=[TextRun(text="Таблица Результаты")])
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert len(found) == 1


def test_b03_multilevel_number_ok() -> None:
    """«Таблица 1.2 — Название» — корректно."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1.2 — Сравнение")],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert found == []


def test_b03_empty_caption_not_flagged() -> None:
    """Пустая подпись — случай B.01, не дублируем."""
    table = Table(id="t-1", caption=[])
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert found == []


def test_b03_allow_dot_after_number_param() -> None:
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1. Результаты")],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    profile.checks["B.03"].params["allow_dot_after_number"] = True
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert found == []


def test_b03_caption_in_nested_section() -> None:
    """B.03 рекурсивно обходит LogicalSection."""
    table_bad = Table(id="t-deep", caption=[TextRun(text="Таблица 1. Bad")])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Подраздел")],
        children=[table_bad],
    )
    outer = LogicalSection(
        id="sec-1",
        level=1,
        heading=[TextRun(text="Раздел")],
        children=[inner],
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.03"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-deep"


# --- B.09 (сквозная нумерация таблиц) ------------------------------------


def test_b09_registered() -> None:
    assert "B.09" in registered_checks()


def test_b09_continuous_numbering_no_violation() -> None:
    """Таблицы 1, 2, 3 — нарушения нет."""
    tables = [
        Table(id=f"t-{i}", caption=[TextRun(text=f"Таблица {i} — Имя {i}")]) for i in (1, 2, 3)
    ]
    doc = _doc_with_content(list(tables))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.09"]
    assert found == []


def test_b09_gap_in_numbering_violation() -> None:
    """Таблицы 1, 3 — пропуск второго номера."""
    tables = [
        Table(id="t-1", caption=[TextRun(text="Таблица 1 — A")]),
        Table(id="t-3", caption=[TextRun(text="Таблица 3 — C")]),
    ]
    doc = _doc_with_content(list(tables))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.09"]
    assert len(found) == 1
    assert found[0].details["expected"] == "2"
    assert found[0].details["found"] == "3"


def test_b09_duplicate_number_violation() -> None:
    """Две таблицы с номером 1 — нарушение «дубликат»."""
    tables = [
        Table(id="t-a", caption=[TextRun(text="Таблица 1 — A")]),
        Table(id="t-b", caption=[TextRun(text="Таблица 1 — B")]),
    ]
    doc = _doc_with_content(list(tables))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.09"]
    assert len(found) == 1
    assert "встречается у двух" in found[0].message
    assert found[0].details["duplicate_of"] == "t-a"


def test_b09_starts_not_from_one_violation() -> None:
    """Первая таблица — 2, должна быть 1."""
    tables = [
        Table(id="t-2", caption=[TextRun(text="Таблица 2 — B")]),
        Table(id="t-3", caption=[TextRun(text="Таблица 3 — C")]),
    ]
    doc = _doc_with_content(list(tables))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.09"]
    assert any(v.details.get("expected") == "1" for v in found)


def test_b09_empty_caption_skipped() -> None:
    """Пустые подписи — это случай B.01, не учитываются в B.09."""
    tables = [
        Table(id="t-1", caption=[TextRun(text="Таблица 1 — A")]),
        Table(id="t-2", caption=[]),  # пустая, не считается
        Table(id="t-2b", caption=[TextRun(text="Таблица 2 — B")]),
    ]
    doc = _doc_with_content(list(tables))
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.09"]
    assert found == []


def test_b09_nested_logical_sections() -> None:
    """Таблицы во вложенных секциях тоже участвуют в сквозной нумерации."""
    t1 = Table(id="t-1", caption=[TextRun(text="Таблица 1 — A")])
    t3 = Table(id="t-3", caption=[TextRun(text="Таблица 3 — C")])
    inner = LogicalSection(id="sec-2", level=2, heading=[TextRun(text="Sub")], children=[t3])
    outer = LogicalSection(
        id="sec-1", level=1, heading=[TextRun(text="Main")], children=[t1, inner]
    )
    doc = _doc_with_content([outer])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.09"]
    assert len(found) == 1
    assert found[0].details["found"] == "3"


def test_b09_no_tables_no_violation() -> None:
    """Документ без таблиц — нет нарушений."""
    doc = _doc_with_content([])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.09"]
    assert found == []


# --- B.08 (на каждую таблицу есть ссылка в тексте) ----------------------


def test_b08_registered() -> None:
    assert "B.08" in registered_checks()


def test_b08_reference_in_text_no_violation() -> None:
    """В тексте есть «в таблице 1» — нарушения нет."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Результаты")])
    para = Paragraph(
        id="p-1",
        content=[TextRun(text="Результаты показаны в таблице 1.")],
    )
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert found == []


def test_b08_no_reference_violation() -> None:
    """Таблица есть, ссылки в тексте нет — нарушение."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Результаты")])
    para = Paragraph(id="p-1", content=[TextRun(text="Просто текст.")])
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-1"
    assert found[0].details["number"] == "1"


def test_b08_reference_abbreviated_form() -> None:
    """«табл. 1» — тоже ссылка."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Результаты")])
    para = Paragraph(id="p-1", content=[TextRun(text="См. табл. 1.")])
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert found == []


def test_b08_caption_itself_does_not_count() -> None:
    """Подпись таблицы «Таблица 1 — ...» сама по себе не считается ссылкой.

    Иначе B.08 никогда бы не находил нарушений, потому что caption всегда
    содержит «Таблица N».
    """
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Результаты")])
    # Никаких Paragraph со ссылками — есть только caption у таблицы.
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-1"


def test_b08_multiple_tables_some_referenced() -> None:
    """Несколько таблиц — нарушения только у тех, на которые нет ссылок."""
    t1 = Table(id="t-1", caption=[TextRun(text="Таблица 1 — A")])
    t2 = Table(id="t-2", caption=[TextRun(text="Таблица 2 — B")])
    para = Paragraph(id="p-1", content=[TextRun(text="См. таблицу 1.")])
    doc = _doc_with_content([para, t1, t2])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-2"


def test_b08_empty_caption_skipped() -> None:
    """Пустые подписи — это случай B.01, для B.08 пропускаются."""
    table = Table(id="t-1", caption=[])
    para = Paragraph(id="p-1", content=[TextRun(text="Просто текст.")])
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert found == []


def test_b08_case_insensitive() -> None:
    """«В Таблице 1» (с большой буквы) — тоже ссылка."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — A")])
    para = Paragraph(id="p-1", content=[TextRun(text="В Таблице 1 указаны данные.")])
    doc = _doc_with_content([para, table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert found == []


def test_b08_reference_in_nested_section() -> None:
    """Ссылка во вложенной секции находится."""
    t1 = Table(id="t-1", caption=[TextRun(text="Таблица 1 — A")])
    inner = LogicalSection(
        id="sec-2",
        level=2,
        heading=[TextRun(text="Sub")],
        children=[Paragraph(id="p-1", content=[TextRun(text="См. таблицу 1.")])],
    )
    doc = _doc_with_content([t1, inner])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.08"]
    assert found == []


# --- B.02 (заглушка) -----------------------------------------------------


def test_b02_registered() -> None:
    """Заглушка B.02 зарегистрирована в реестре."""
    assert "B.02" in registered_checks()


# --- B.04 (заглушка) -----------------------------------------------------


def test_b04_registered() -> None:
    """Заглушка B.04 зарегистрирована в реестре."""
    assert "B.04" in registered_checks()


# --- B.05 (заглушка) -----------------------------------------------------


def test_b05_registered() -> None:
    """Заглушка B.05 зарегистрирована в реестре."""
    assert "B.05" in registered_checks()


# --- B.06 (шрифт 12pt в ячейках) ----------------------------------------


def test_b06_registered() -> None:
    """Проверка B.06 зарегистрирована в реестре."""
    assert "B.06" in registered_checks()


def test_b06_correct_font_size_no_violation() -> None:
    """Все ячейки 12pt — нарушения нет."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="H", size_pt=12.0)]],
        rows=[[[TextRun(text="C", size_pt=12.0)]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.06"]
    assert found == []


def test_b06_wrong_font_size_violation() -> None:
    """Ячейка 14pt вместо 12pt — нарушение."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="H", size_pt=12.0)]],
        rows=[[[TextRun(text="C", size_pt=14.0)]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.06"]
    assert len(found) == 1
    assert found[0].details["table_id"] == "t-1"
    assert found[0].details["found_pt"] == "14.0"


def test_b06_none_size_not_checked() -> None:
    """TextRun с size_pt=None — наследуется от стиля, не проверяется."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="H")]],
        rows=[[[TextRun(text="C")]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.06"]
    assert found == []


def test_b06_param_override() -> None:
    """Параметр cell_font_size_pt=10 принимает 10pt и отвергает 12pt."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="H", size_pt=12.0)]],
        rows=[[[TextRun(text="C", size_pt=12.0)]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    profile.checks["B.06"].params["cell_font_size_pt"] = 10
    found = [v for v in validate(doc, profile) if v.check_code == "B.06"]
    assert len(found) == 1
    assert found[0].details["found_pt"] == "12.0"


# --- B.07 (пустые ячейки заполнены прочерком) ---------------------------


def test_b07_registered() -> None:
    """Проверка B.07 зарегистрирована в реестре."""
    assert "B.07" in registered_checks()


def test_b07_no_empty_cells_no_violation() -> None:
    """Все ячейки заполнены — нарушения нет."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="H1")], [TextRun(text="H2")]],
        rows=[
            [[TextRun(text="1")], [TextRun(text="2")]],
            [[TextRun(text="3")], [TextRun(text="—")]],
        ],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.07"]
    assert found == []


def test_b07_empty_cell_violation() -> None:
    """Пустая ячейка в данных — нарушение."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="H1")], [TextRun(text="H2")]],
        rows=[
            [[TextRun(text="1")], [TextRun(text="2")]],
            [[TextRun(text="3")], [TextRun(text="  ")]],  # пустая
        ],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.07"]
    assert len(found) == 1
    assert found[0].details["row"] == "2"
    assert found[0].details["col"] == "1"


def test_b07_allow_first_column_empty() -> None:
    """allow_first_column_empty=True пропускает пустые ячейки col 0."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="")], [TextRun(text="H2")]],  # col 0 пуст
        rows=[
            [[TextRun(text="")], [TextRun(text="2")]],  # col 0 пуст
        ],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    profile.checks["B.07"].params["allow_first_column_empty"] = True
    found = [v for v in validate(doc, profile) if v.check_code == "B.07"]
    assert found == []


def test_b07_empty_header_cell_violation() -> None:
    """Пустая ячейка в шапке (row 0) — тоже нарушение."""
    table = Table(
        id="t-1",
        caption=[TextRun(text="Таблица 1 — A")],
        headers=[[TextRun(text="H1")], []],  # col 1 шапки пуст
        rows=[[[TextRun(text="1")], [TextRun(text="2")]]],
    )
    doc = _doc_with_content([table])
    profile = load_profile("gost-7.32-2017")
    found = [v for v in validate(doc, profile) if v.check_code == "B.07"]
    assert len(found) == 1
    assert found[0].details["row"] == "0"
    assert found[0].details["col"] == "1"


# --- B.11 — таблица после первого упоминания в тексте -----------------------


def test_b11_registered() -> None:
    assert "B.11" in registered_checks()


def test_b11_reference_before_table_ok() -> None:
    """Упоминание до таблицы — нарушения нет."""
    para = Paragraph(id="p-1", content=[TextRun(text="В таблице 1 приведены данные.")])
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Результаты")])
    doc = _doc_with_content([para, table])
    found = [v for v in validate(doc, load_profile("gost-7.32-2017")) if v.check_code == "B.11"]
    assert found == []


def test_b11_reference_after_table_warns() -> None:
    """Упоминание только после таблицы — B.11 warning."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Результаты")])
    para = Paragraph(id="p-2", content=[TextRun(text="Как показано в таблице 1, ...")])
    doc = _doc_with_content([table, para])
    found = [v for v in validate(doc, load_profile("gost-7.32-2017")) if v.check_code == "B.11"]
    assert len(found) == 1
    assert found[0].severity == "warning"
    assert found[0].details["number"] == "1"


def test_b11_no_reference_is_b08_not_b11() -> None:
    """Если ссылок нет совсем — это B.08, B.11 не срабатывает."""
    table = Table(id="t-1", caption=[TextRun(text="Таблица 1 — Результаты")])
    doc = _doc_with_content([table])
    found = [v for v in validate(doc, load_profile("gost-7.32-2017")) if v.check_code == "B.11"]
    assert found == []
