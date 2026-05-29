"""Тесты авто-наполнения списка литературы ГОСТами/ФЗ (gostforge.autocite)."""

from __future__ import annotations

from gostforge.autocite import autofill_references
from gostforge.builder import work
from gostforge.model import (
    BibliographyEntry,
    Document,
    LogicalSection,
    PageSection,
    Paragraph,
    TextRun,
)


def _doc_with_body_and_bib(body: str, bib_refs: list[str] | None = None) -> Document:
    """Документ: один раздел с текстом + раздел «Список литературы»."""
    body_sec = LogicalSection(
        id="s1",
        heading=[TextRun(text="Введение")],
        level=1,
        children=[Paragraph(id="p1", content=[TextRun(text=body)])],
    )
    bib_children: list[object] = []
    for i, ref in enumerate(bib_refs or []):
        bib_children.append(Paragraph(id=f"ref-{i}", content=[TextRun(text=ref)]))
    bib_sec = LogicalSection(
        id="bib",
        heading=[TextRun(text="Список использованных источников")],
        level=1,
        children=bib_children,  # type: ignore[arg-type]
    )
    doc = Document()
    doc.page_sections.append(
        PageSection(id="main", name="m", type="main", content=[body_sec, bib_sec])
    )
    # bibliography metadata (как после парсинга/extract)
    for i, ref in enumerate(bib_refs or []):
        doc.bibliography.append(BibliographyEntry(id=f"ref-{i}", type="book", fields={"raw": ref}))
    return doc


def test_adds_gost_from_body() -> None:
    doc = _doc_with_body_and_bib("Работа выполнена по ГОСТ 7.32-2017 и ГОСТ Р 2.105-2019.")
    added = autofill_references(doc)
    designations = {e.fields["designation"] for e in added}
    assert "ГОСТ 7.32-2017" in designations
    assert "ГОСТ Р 2.105-2019" in designations
    assert all(e.type == "standard" for e in added)
    # год извлечён из обозначения
    g = next(e for e in added if e.fields["designation"] == "ГОСТ 7.32-2017")
    assert g.fields["year"] == "2017"


def test_adds_fz_with_and_without_date() -> None:
    doc = _doc_with_body_and_bib(
        "Согласно Федеральному закону от 27.07.2006 № 152-ФЗ, а также № 149-ФЗ."
    )
    added = autofill_references(doc)
    laws = {e.fields["designation"]: e for e in added if e.type == "law"}
    assert "№152-ФЗ" in laws
    assert "№149-ФЗ" in laws
    assert laws["№152-ФЗ"].fields.get("year") == "2006"


def test_idempotent_no_duplicates_on_rebuild() -> None:
    """Повторный вызов не добавляет уже присутствующие записи."""
    doc = _doc_with_body_and_bib("Текст по ГОСТ 7.32-2017.")
    first = autofill_references(doc)
    assert len(first) == 1
    # имитируем «пересборку»: запись уже в библиографии и в разделе
    second = autofill_references(doc)
    assert second == []
    # ровно одна запись ГОСТа в библиографии
    gosts = [e for e in doc.bibliography if e.fields.get("designation") == "ГОСТ 7.32-2017"]
    assert len(gosts) == 1


def test_dedup_against_existing_bibliography() -> None:
    """Если ГОСТ уже в списке (другим форматированием) — не дублируется."""
    doc = _doc_with_body_and_bib(
        "Текст по ГОСТ 7.32-2017.",
        bib_refs=["ГОСТ 7.32–2017. — Москва : Стандартинформ, 2017."],  # en-dash
    )
    added = autofill_references(doc)
    assert added == []


def test_adds_paragraph_to_bibliography_section() -> None:
    """Добавленная запись появляется абзацем в разделе библиографии."""
    doc = _doc_with_body_and_bib("Текст по ГОСТ 2.104-2006.")
    autofill_references(doc)
    bib = next(
        c for c in doc.page_sections[0].content if isinstance(c, LogicalSection) and c.id == "bib"
    )
    texts = [
        "".join(el.text for el in p.content if isinstance(el, TextRun))
        for p in bib.children
        if isinstance(p, Paragraph)
    ]
    assert any("ГОСТ 2.104-2006" in t for t in texts)


def test_no_mentions_no_changes() -> None:
    doc = _doc_with_body_and_bib("Обычный текст без нормативных ссылок.")
    assert autofill_references(doc) == []


def test_builder_toggle_autofill() -> None:
    """WorkBuilder.autofill_references() добавляет ГОСТ при build()."""
    doc = (
        work("Работа")
        .autofill_references()
        .section("Введение")
        .paragraph("Выполнено по ГОСТ 7.32-2017.")
        .section("Список использованных источников")
        .build()
    )
    designations = {e.fields.get("designation") for e in doc.bibliography}
    assert "ГОСТ 7.32-2017" in designations


def test_builder_without_toggle_no_autofill() -> None:
    doc = (
        work("Работа")
        .section("Введение")
        .paragraph("Выполнено по ГОСТ 7.32-2017.")
        .section("Список использованных источников")
        .build()
    )
    assert all(e.fields.get("designation") != "ГОСТ 7.32-2017" for e in doc.bibliography)


def test_known_gost_full_title_format() -> None:
    """Известный ГОСТ описывается с официальным названием и видом носителя."""
    doc = _doc_with_body_and_bib("Оформление по ГОСТ 7.32-2017.")
    added = autofill_references(doc)
    raw = added[0].fields["raw"]
    assert "Отчёт о научно-исследовательской работе" in raw
    assert "Москва : Стандартинформ, 2017" in raw
    assert raw.endswith("Текст : непосредственный.")


def test_unknown_gost_minimal_format() -> None:
    """Неизвестный ГОСТ — корректный минимальный скелет без выдуманного названия."""
    doc = _doc_with_body_and_bib("По ГОСТ 9999-2000.")
    added = autofill_references(doc)
    raw = added[0].fields["raw"]
    assert raw == "ГОСТ 9999-2000. — Москва : Стандартинформ, 2000. — Текст : непосредственный."


def test_known_fz_title_and_catalog_date() -> None:
    """Известный ФЗ (без даты в тексте) описывается с названием и датой из каталога."""
    doc = _doc_with_body_and_bib("Регулируется № 273-ФЗ.")
    added = autofill_references(doc)
    law = next(e for e in added if e.fields["designation"] == "№273-ФЗ")
    assert "Об образовании в Российской Федерации" in law.fields["raw"]
    assert "29.12.2012" in law.fields["raw"]
    assert law.fields["year"] == "2012"


def test_insert_citations_adds_reference_in_paragraph() -> None:
    """insert_citations=True добавляет Citation в упоминающий абзац."""
    from gostforge.model import Citation

    doc = _doc_with_body_and_bib("Работа выполнена по ГОСТ 7.32-2017.")
    added = autofill_references(doc, insert_citations=True)
    gost = next(e for e in added if e.fields["designation"] == "ГОСТ 7.32-2017")
    body_para = doc.page_sections[0].content[0].children[0]  # type: ignore[attr-defined]
    cites = [el for el in body_para.content if isinstance(el, Citation)]
    assert any(c.source_id == gost.id for c in cites)


def test_insert_citations_idempotent() -> None:
    """Повторный вызов не добавляет вторую Citation на тот же источник."""
    from gostforge.model import Citation

    doc = _doc_with_body_and_bib("По ГОСТ 7.32-2017.")
    autofill_references(doc, insert_citations=True)
    autofill_references(doc, insert_citations=True)
    body_para = doc.page_sections[0].content[0].children[0]  # type: ignore[attr-defined]
    cites = [el for el in body_para.content if isinstance(el, Citation)]
    assert len(cites) == 1


def test_no_citations_without_flag() -> None:
    from gostforge.model import Citation

    doc = _doc_with_body_and_bib("По ГОСТ 7.32-2017.")
    autofill_references(doc)  # insert_citations=False по умолчанию
    body_para = doc.page_sections[0].content[0].children[0]  # type: ignore[attr-defined]
    assert not any(isinstance(el, Citation) for el in body_para.content)
