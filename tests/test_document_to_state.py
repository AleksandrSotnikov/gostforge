"""Тесты обратного преобразования Document → state-dict конструктора.

Это позволяет студенту загрузить чужой .docx в конструктор и
продолжить редактирование. Покрытие:

* round-trip state → Document → state — данные не теряются;
* docx → parse → document_to_state — состав sections правильный;
* библиографический раздел: parsed.bibliography → state.references;
* disabled_checks (если есть в Document) — сохраняются;
* пустой документ → пустой sections.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.model import (
    BibliographyEntry,
    Document,
    DocumentMetadata,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    TextRun,
)
from gostforge.parser import parse_docx
from gostforge.profile import load_profile
from gostforge.web.builder_editor import (
    _build_document_from_state,
    document_to_state,
)

# --- Smoke ---


def test_document_to_state_rejects_non_document() -> None:
    with pytest.raises(TypeError):
        document_to_state({"not": "a document"})


def test_empty_document_to_state() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    state = document_to_state(doc)
    assert state["title"] == "X"
    assert state["sections"] == []
    assert state["profile_id"] == "gost-7.32-2017"  # fallback


def test_metadata_preserved() -> None:
    doc = Document(
        metadata=DocumentMetadata(
            title="Курсовая",
            author="Иванов И. И.",
            supervisor="Петров П. П.",
            organization="МГТУ",
            year=2026,
            work_type="thesis",
        ),
        profile_id="gost-r-2.105-2019",
    )
    state = document_to_state(doc)
    assert state["title"] == "Курсовая"
    assert state["author"] == "Иванов И. И."
    assert state["supervisor"] == "Петров П. П."
    assert state["organization"] == "МГТУ"
    assert state["year"] == 2026
    assert state["work_type"] == "thesis"
    assert state["profile_id"] == "gost-r-2.105-2019"


# --- Round-trip через builder ---


def test_roundtrip_simple_section() -> None:
    """state → build → document_to_state → данные совпадают."""
    state_in = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [
                    {"kind": "paragraph", "text": "Актуальность темы."},
                    {"kind": "paragraph", "text": "Цель работы — X."},
                ],
            }
        ],
    }
    data = _build_document_from_state(state_in)
    # Документ собрался — теперь экспортируем во временный файл и парсим.
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(data)
        path = Path(f.name)
    doc = parse_docx(path)
    state_out = document_to_state(doc)
    # Найти секцию «Введение» (текст может быть в uppercase или нет).
    intro = next(
        (s for s in state_out["sections"] if "введ" in s["heading"].lower()),
        None,
    )
    assert intro is not None, (
        f"Введение не найдено в {[s['heading'] for s in state_out['sections']]}"
    )
    texts = [b.get("text", "") for b in intro["blocks"] if b.get("kind") == "paragraph"]
    assert "Актуальность темы." in texts
    assert "Цель работы — X." in texts


def test_roundtrip_table() -> None:
    state_in = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Анализ",
                "blocks": [
                    {
                        "kind": "table",
                        "headers": ["Алгоритм", "Сложность"],
                        "rows": [["Быстрая", "O(n log n)"]],
                        "caption": "Сложность",
                    }
                ],
            }
        ],
    }
    data = _build_document_from_state(state_in)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(data)
        path = Path(f.name)
    doc = parse_docx(path)
    state_out = document_to_state(doc)
    sec = next(s for s in state_out["sections"] if "анализ" in s["heading"].lower())
    tables = [b for b in sec["blocks"] if b.get("kind") == "table"]
    assert tables, f"Таблица потеряна. Блоки: {sec['blocks']}"
    tbl = tables[0]
    assert tbl["headers"] == ["Алгоритм", "Сложность"]
    assert tbl["rows"] == [["Быстрая", "O(n log n)"]]
    assert "Сложность" in tbl["caption"]


def test_roundtrip_list_preserves_as_list_block() -> None:
    """После добавления _group_text_marker_lists парсер собирает
    подряд идущие маркированные параграфы обратно в ListBlock —
    round-trip list↔list работает без потерь."""
    state_in = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Перечисление",
                "blocks": [
                    {
                        "kind": "list",
                        "ordered": False,
                        "items": ["один", "два", "три"],
                    }
                ],
            }
        ],
    }
    data = _build_document_from_state(state_in)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(data)
        path = Path(f.name)
    doc = parse_docx(path)
    state_out = document_to_state(doc)
    sec = next(s for s in state_out["sections"] if "перечисл" in s["heading"].lower())
    lists = [b for b in sec["blocks"] if b.get("kind") == "list"]
    assert lists, f"Список не собрался обратно. Блоки: {sec['blocks']}"
    assert lists[0]["items"] == ["один", "два", "три"]
    assert lists[0]["ordered"] is False


# --- Bibliography ---


def test_bibliography_section_detected() -> None:
    """LogicalSection с заголовком 'Список ...' помечается is_bibliography."""
    doc = Document(metadata=DocumentMetadata(title="X"))
    bib_section = LogicalSection(
        id="sec-bib",
        heading=[TextRun(text="Список использованных источников")],
        level=1,
        children=[
            Paragraph(
                id="p",
                content=[TextRun(text="Кнут Д. — М. : Вильямс, 2007. — 832 с.")],
            ),
            Paragraph(
                id="p",
                content=[TextRun(text="ГОСТ 7.32-2017. — М. : Стандартинформ.")],
            ),
        ],
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[bib_section],
        )
    )
    state = document_to_state(doc)
    sec = state["sections"][0]
    assert sec.get("is_bibliography") is True
    assert len(sec.get("references", [])) == 2
    assert "Кнут" in sec["references"][0]


def test_bibliography_from_document_field_when_no_section() -> None:
    """Если bib только в document.bibliography (плоский список),
    в state создаётся отдельная bib-секция."""
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.bibliography = [
        BibliographyEntry(
            id="ref-1",
            type="book",
            fields={"raw": "Кнут Д. Э. — М., 2007."},
        ),
        BibliographyEntry(
            id="ref-2",
            type="book",
            fields={"raw": "Кормен. — М., 2013."},
        ),
    ]
    state = document_to_state(doc)
    bib_secs = [s for s in state["sections"] if s.get("is_bibliography")]
    assert len(bib_secs) == 1
    assert len(bib_secs[0]["references"]) == 2


# --- disabled_checks сохраняется ---


def test_disabled_checks_preserved_in_state() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[
                LogicalSection(
                    id="sec-titul",
                    heading=[TextRun(text="Титульный лист")],
                    level=1,
                    disabled_checks=["*"],
                ),
                LogicalSection(
                    id="sec-appendix",
                    heading=[TextRun(text="Приложение А")],
                    level=1,
                    disabled_checks=["H.01", "T.04"],
                ),
            ],
        )
    )
    state = document_to_state(doc)
    titul = state["sections"][0]
    appendix = state["sections"][1]
    assert titul["disabled_checks"] == ["*"]
    assert "H.01" in appendix["disabled_checks"]
    assert "T.04" in appendix["disabled_checks"]


# --- Sub-sections ---


def test_subsections_preserved() -> None:
    doc = Document(metadata=DocumentMetadata(title="X"))
    parent = LogicalSection(
        id="sec-1",
        heading=[TextRun(text="Глава 1")],
        level=1,
        children=[
            LogicalSection(
                id="sec-1-1",
                heading=[TextRun(text="1.1 Подраздел")],
                level=2,
                children=[
                    Paragraph(id="p-sub", content=[TextRun(text="текст подраздела")]),
                ],
            )
        ],
    )
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная",
            type="main",
            page=PageGeometry(),
            page_numbering=PageNumberingConfig(),
            content=[parent],
        )
    )
    state = document_to_state(doc)
    sec = state["sections"][0]
    assert len(sec["subsections"]) == 1
    sub = sec["subsections"][0]
    assert "1.1" in sub["heading"]
    assert any(
        b.get("text") == "текст подраздела" for b in sub["blocks"] if b.get("kind") == "paragraph"
    )


# --- End-to-end через реальный builder + parse ---


def test_builder_save_then_load_back_into_state(tmp_path: Path) -> None:
    """Сценарий «генерация → парс → загрузка в конструктор»."""
    b = (
        work("Курсовая работа", author="Иванов И. И.", year=2026)
        .section("Введение")
        .paragraph("Актуальность темы исследования.")
        .paragraph("Цель работы — разработать систему.")
        .section("1 Анализ")
        .paragraph("Анализ существующих решений.")
        .list(["требование 1", "требование 2"], ordered=False)
        .section("Заключение")
        .paragraph("Результаты получены.")
        .section("Список использованных источников")
        .reference("Кнут Д. — М. : Вильямс, 2007. — 832 с.")
    )
    doc = b.build()
    profile = load_profile("gost-7.32-2017")
    out = tmp_path / "demo.docx"
    export_docx(doc, profile, out)

    parsed = parse_docx(out)
    parsed.profile_id = "gost-7.32-2017"
    state = document_to_state(parsed)

    # Метаданные.
    assert state["title"] == "Курсовая работа"
    assert state["author"] == "Иванов И. И."
    assert state["year"] == 2026  # экспортёр пишет в core.created

    # Разделы: Введение, 1 Анализ, Заключение, Список — в любом порядке/регистре.
    headings = [s["heading"].lower() for s in state["sections"]]
    assert any("введ" in h for h in headings)
    assert any("анализ" in h for h in headings)
    assert any("заключ" in h for h in headings)
    assert any("список" in h for h in headings)

    # Bib-секция содержит ровно 1 source.
    bib = next(s for s in state["sections"] if s.get("is_bibliography"))
    assert len(bib["references"]) == 1
    assert "Кнут" in bib["references"][0]


def test_load_into_state_then_export_back(tmp_path: Path) -> None:
    """Полный круг: docx → state → docx — результат остаётся валидным."""
    # Шаг 1: оригинальный docx.
    b = (
        work("X", author="A", year=2026)
        .section("Введение")
        .paragraph("текст один")
        .paragraph("текст два")
        .section("Список использованных источников")
        .reference("Кнут. — М., 2007.")
    )
    doc1 = b.build()
    profile = load_profile("gost-7.32-2017")
    out1 = tmp_path / "step1.docx"
    export_docx(doc1, profile, out1)

    # Шаг 2: разложить в state.
    parsed = parse_docx(out1)
    state = document_to_state(parsed)

    # Шаг 3: пересобрать обратно.
    data2 = _build_document_from_state(state)
    out2 = tmp_path / "step2.docx"
    out2.write_bytes(data2)

    # Шаг 4: распарсить ещё раз — основные элементы сохранились.
    parsed2 = parse_docx(out2)
    state2 = document_to_state(parsed2)
    headings1 = sorted(s["heading"].lower() for s in state["sections"])
    headings2 = sorted(s["heading"].lower() for s in state2["sections"])
    assert headings1 == headings2
