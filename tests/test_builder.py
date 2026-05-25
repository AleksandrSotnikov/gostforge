"""Тесты конструктора работ."""

from __future__ import annotations

from pathlib import Path

import pytest

from gostforge.builder import WorkBuilder, work
from gostforge.model import (
    BibliographyEntry,
    Document,
    Figure,
    LogicalSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.parser import parse_docx
from gostforge.profile import load_profile
from gostforge.validator import validate


def _heading_text(section: LogicalSection) -> str:
    return "".join(el.text for el in section.heading if isinstance(el, TextRun))


def _paragraph_text(para: Paragraph) -> str:
    return "".join(el.text for el in para.content if isinstance(el, TextRun))


def _top_level_sections(doc: Document) -> list[LogicalSection]:
    sections: list[LogicalSection] = []
    for ps in doc.page_sections:
        for child in ps.content:
            if isinstance(child, LogicalSection):
                sections.append(child)
    return sections


# --- Базовая сборка ----------------------------------------------------------


def test_work_builder_creates_document() -> None:
    doc = work("Title", author="Иванов И. И.", year=2026).build()
    assert isinstance(doc, Document)
    assert doc.metadata.title == "Title"
    assert doc.metadata.author == "Иванов И. И."
    assert doc.metadata.year == 2026
    assert doc.metadata.work_type == "coursework"


def test_section_adds_logical_section() -> None:
    doc = work("T").section("Введение").build()
    sections = _top_level_sections(doc)
    assert len(sections) == 1
    assert sections[0].level == 1
    assert _heading_text(sections[0]).upper() == "ВВЕДЕНИЕ"


def test_paragraph_adds_content() -> None:
    doc = work("T").section("Введение").paragraph("Текст параграфа").build()
    section = _top_level_sections(doc)[0]
    paragraphs = [c for c in section.children if isinstance(c, Paragraph)]
    assert len(paragraphs) == 1
    assert _paragraph_text(paragraphs[0]) == "Текст параграфа"


def test_chained_paragraphs_stay_in_same_section() -> None:
    doc = (
        work("T")
        .section("Введение")
        .paragraph("Первый")
        .paragraph("Второй")
        .paragraph("Третий")
        .build()
    )
    section = _top_level_sections(doc)[0]
    paragraphs = [c for c in section.children if isinstance(c, Paragraph)]
    assert [_paragraph_text(p) for p in paragraphs] == ["Первый", "Второй", "Третий"]


def test_subsection_nests_under_current_section() -> None:
    doc = (
        work("T")
        .section("Глава 1")
        .subsection("1.1 Подраздел")
        .paragraph("Текст подраздела")
        .build()
    )
    sections = _top_level_sections(doc)
    assert len(sections) == 1
    parent = sections[0]
    assert parent.level == 1
    subs = [c for c in parent.children if isinstance(c, LogicalSection)]
    assert len(subs) == 1
    assert subs[0].level == 2
    assert _heading_text(subs[0]) == "1.1 Подраздел"
    sub_paras = [c for c in subs[0].children if isinstance(c, Paragraph)]
    assert [_paragraph_text(p) for p in sub_paras] == ["Текст подраздела"]


def test_new_section_resets_paragraphs_target() -> None:
    doc = (
        work("T")
        .section("A")
        .paragraph("x")
        .section("B")
        .paragraph("y")
        .build()
    )
    sections = _top_level_sections(doc)
    assert [_heading_text(s) for s in sections] == ["A", "B"]
    a_paras = [c for c in sections[0].children if isinstance(c, Paragraph)]
    b_paras = [c for c in sections[1].children if isinstance(c, Paragraph)]
    assert [_paragraph_text(p) for p in a_paras] == ["x"]
    assert [_paragraph_text(p) for p in b_paras] == ["y"]


# --- Сборка: разрыв страницы и нумерация -------------------------------------


def test_build_sets_page_break_before_for_non_first_section() -> None:
    doc = (
        work("T")
        .section("A")
        .paragraph("a1")
        .section("B")
        .paragraph("b1")
        .section("C")
        .paragraph("c1")
        .build()
    )
    sections = _top_level_sections(doc)
    a_paras = [c for c in sections[0].children if isinstance(c, Paragraph)]
    b_paras = [c for c in sections[1].children if isinstance(c, Paragraph)]
    c_paras = [c for c in sections[2].children if isinstance(c, Paragraph)]
    # Первый раздел — на первой странице, без принудительного разрыва.
    assert a_paras[0].page_break_before is None or a_paras[0].page_break_before is False
    # Остальные — с разрывом.
    assert b_paras[0].page_break_before is True
    assert c_paras[0].page_break_before is True


def test_build_sets_footer_and_start_value() -> None:
    doc = work("T").section("Введение").paragraph("...").build()
    assert len(doc.page_sections) == 1
    ps = doc.page_sections[0]
    assert ps.type == "main"
    assert ps.footer is not None
    assert ps.footer.default.center is not None
    center = ps.footer.default.center
    assert isinstance(center[0], TextRun)
    assert center[0].text == "{page}"
    assert ps.page_numbering.start_mode == "start_at"
    assert ps.page_numbering.start_value == 3


# --- Валидация ---------------------------------------------------------------


def test_built_document_passes_validation() -> None:
    """Документ конструктора не должен иметь error-нарушений.

    Сейчас активна только F.01 (поля страницы) — наш PageSection ставит
    правильные поля, поэтому ошибок быть не должно.
    """
    doc = (
        work("Курсовая", author="Иванов", year=2026)
        .section("Введение")
        .paragraph("Актуальность темы")
        .section("Заключение")
        .paragraph("Итог")
        .section("Список использованных источников")
        .build()
    )
    profile = load_profile("gost-7.32-2017")
    violations = validate(doc, profile)
    errors = [v for v in violations if v.severity == "error"]
    assert errors == [], f"Найдены ошибки: {[(v.check_code, v.message) for v in errors]}"


# --- Сохранение --------------------------------------------------------------


def test_save_writes_docx(tmp_path: Path) -> None:
    out = tmp_path / "out.docx"
    builder = (
        work("Курсовая по нормоконтролю", author="Иванов И. И.", year=2026)
        .section("Введение")
        .paragraph("Актуальность темы")
        .section("Заключение")
        .paragraph("Итог")
        .section("Список использованных источников")
        .root
    )
    builder.save(out, profile="gost-7.32-2017")
    assert out.exists()
    assert out.stat().st_size > 0
    parsed = parse_docx(out)
    # Парсер сейчас стаб: берёт title из имени файла. Проверяем, что .docx
    # вообще читается без исключений.
    assert parsed.metadata.title


def test_save_raises_on_validation_errors(tmp_path: Path) -> None:
    """Пустой WorkBuilder с неправильными полями страницы должен падать на validate.

    Чтобы это смоделировать на текущем наборе проверок (F.01), мутируем
    PageSection после build() и проверяем save() отдельно через прямой
    вызов экспортёра. Для самого save() — собираем builder и подменяем
    геометрию в build().
    """
    # Создаём корневой WorkBuilder и патчим его build(), чтобы сломать поля
    # страницы и тем самым спровоцировать F.01 на validate().
    root = work("Empty work")
    root.section("Введение").paragraph("...")
    out = tmp_path / "bad.docx"

    original_build = root.build

    def broken_build() -> Document:
        doc = original_build()
        doc.page_sections[0].page.margins_mm["top"] = 10.0  # неверно
        return doc

    root.build = broken_build  # type: ignore[method-assign]

    with pytest.raises(ValueError, match=r"F\.01"):
        root.save(out, profile="gost-7.32-2017")


# --- Таблицы, рисунки, ссылки ------------------------------------------------


def test_table_and_figure_added_to_section() -> None:
    doc = (
        work("T")
        .section("A")
        .table(headers=["h1", "h2"], rows=[["a", "b"], ["c", "d"]], caption="Test")
        .figure(image_path="x.png", caption="Schema")
        .build()
    )
    section = _top_level_sections(doc)[0]
    tables = [c for c in section.children if isinstance(c, Table)]
    figures = [c for c in section.children if isinstance(c, Figure)]
    assert len(tables) == 1
    assert len(figures) == 1
    assert tables[0].number == 1
    assert figures[0].number == 1
    assert isinstance(tables[0].caption[0], TextRun)
    assert tables[0].caption[0].text.startswith("Таблица 1 — ")
    assert isinstance(figures[0].caption[0], TextRun)
    assert figures[0].caption[0].text.startswith("Рисунок 1 — ")


def test_reference_in_bibliography_section() -> None:
    doc = (
        work("T")
        .section("Введение")
        .paragraph("Актуальность")
        .section("Список использованных источников")
        .reference("Иванов И. И. Программирование. — М. : Наука, 2023. — 320 с.")
        .reference("Петров П. П. Алгоритмы. — СПб. : Питер, 2024. — 450 с.", type="book")
        .build()
    )
    assert len(doc.bibliography) == 2
    assert all(isinstance(e, BibliographyEntry) for e in doc.bibliography)
    assert doc.bibliography[0].type == "book"
    assert "Иванов" in doc.bibliography[0].fields["raw"]
    assert "Петров" in doc.bibliography[1].fields["raw"]


def test_reference_outside_bibliography_section_raises() -> None:
    """reference() вне «Списка ...» должен бросать ValueError."""
    builder = work("T").section("Введение")
    with pytest.raises(ValueError, match="reference"):
        builder.reference("Какая-то книга 2024.")


# --- Фабричная функция и тип возвращаемого ----------------------------------


def test_work_factory_returns_work_builder() -> None:
    builder = work("Some")
    assert isinstance(builder, WorkBuilder)
