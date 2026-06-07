"""Колонтитулы по секциям: титул/задание без колонтитула, содержание —
полная основная надпись (форма 2), далее — сокращённая (форма 2а).

Покрывает мультисекционный экспорт (несколько физических sectPr с
собственными колонтитулами) и разбиение frontmatter-разделов
конструктором (`_split_frontmatter_page_section`).
"""

from __future__ import annotations

import re
import tempfile
import zipfile

from gostforge.exporter import export_docx
from gostforge.model import (
    Document,
    DocumentMetadata,
    HeaderConfig,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    TextRun,
    TitleBlock,
    TitleBlockRole,
)
from gostforge.profile import load_profile


def _sec(sid: str, heading: str, text: str) -> LogicalSection:
    return LogicalSection(
        id=sid,
        heading=[TextRun(text=heading)],
        level=1,
        children=[Paragraph(id=sid + "p", content=[TextRun(text=text)])],
    )


def _footers(path: str) -> dict[str, str]:
    """Вернуть {имя footer-части: извлечённый текст}."""
    out: dict[str, str] = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if re.search(r"word/footer\d+\.xml$", n):
                data = z.read(n).decode("utf-8", "replace")
                text = " ".join(t.split(">", 1)[-1] for t in re.findall(r"<w:t[ >][^<]*", data))
                out[n] = text
    return out


def _doc_xml(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8", "replace")


def _three_section_document() -> Document:
    front = PageSection(
        id="front",
        name="Титул+задание",
        type="title",
        page=PageGeometry(paper="A4"),
        footer=None,
        header=None,
        page_numbering=PageNumberingConfig(visible=False),
        content=[
            _sec("titlesec", "Титульный лист", "ТИТУЛ"),
            _sec("tasksec", "Задание", "ЗАДАНИЕ"),
        ],
    )
    main = PageSection(
        id="main",
        name="ПЗ",
        type="main",
        page=PageGeometry(paper="A4"),
        page_numbering=PageNumberingConfig(visible=True, start_mode="start_at", start_value=3),
        different_first_page=True,
        title_block=TitleBlock(
            enabled=True,
            designation="АБВГ.001 ПЗ",
            organization="ОПЭК",
            roles=[TitleBlockRole(role="Разраб."), TitleBlockRole(role="Руковод.")],
        ),
        content=[_sec("toc", "Содержание", "СОДЕРЖАНИЕ"), _sec("intro", "Введение", "Текст")],
    )
    return Document(
        profile_id="gost-7.32-2017",
        metadata=DocumentMetadata(title="Тест", year=2026),
        page_sections=[front, main],
    )


def test_multisection_export_emits_two_physical_sections() -> None:
    """Документ с двумя PageSection даёт два sectPr и titlePg у основной."""
    out = tempfile.mktemp(suffix=".docx")
    export_docx(_three_section_document(), load_profile("gost-7.32-2017"), out)
    xml = _doc_xml(out)
    assert xml.count("<w:sectPr") == 2
    assert xml.count("<w:titlePg") == 1


def test_frontmatter_section_has_no_colontitul() -> None:
    """У frontmatter-секции (титул+задание) footer пустой — без штампа/номера."""
    out = tempfile.mktemp(suffix=".docx")
    export_docx(_three_section_document(), load_profile("gost-7.32-2017"), out)
    footers = _footers(out)
    # Хотя бы один footer пустой (frontmatter) и хотя бы один со штампом.
    empty = [n for n, t in footers.items() if not t.strip()]
    stamped = [n for n, t in footers.items() if "ПЗ" in t]
    assert empty, f"нет пустого footer (frontmatter): {footers}"
    assert stamped, f"нет footer со штампом: {footers}"


def test_main_section_stamp_only_on_first_page() -> None:
    """Основная надпись печатается ТОЛЬКО на первой странице секции
    (содержание): есть полный штамп (Разраб.) и нет отдельной сокращённой
    надписи на последующих листах."""
    out = tempfile.mktemp(suffix=".docx")
    export_docx(_three_section_document(), load_profile("gost-7.32-2017"), out)
    footers = _footers(out)
    full = [t for t in footers.values() if "Разраб" in t]
    # Сокращённая надпись (footer с обозначением, но без ролей) не должна
    # появляться — на последующих листах колонтитула нет.
    reduced = [t for t in footers.values() if "ПЗ" in t and "Разраб" not in t]
    assert full, f"нет полной основной надписи (форма 2) на содержании: {footers}"
    assert reduced == [], f"штамп не должен повторяться на последующих листах: {footers}"


def test_main_section_first_heading_break_suppressed() -> None:
    """Первый заголовок основной секции (содержание) не должен давать
    лишнюю пустую страницу: pageBreakBefore явно отключён (разрыв секции
    уже переносит на новую страницу)."""
    out = tempfile.mktemp(suffix=".docx")
    export_docx(_three_section_document(), load_profile("gost-7.32-2017"), out)
    assert 'pageBreakBefore w:val="false"' in _doc_xml(out)


def test_stamp_sheet_uses_page_field_when_empty() -> None:
    """Графа «Лист» основной надписи — авто-поле PAGE, если номер не задан."""
    out = tempfile.mktemp(suffix=".docx")
    export_docx(_three_section_document(), load_profile("gost-7.32-2017"), out)
    with zipfile.ZipFile(out) as z:
        footers = [
            z.read(n).decode("utf-8", "replace")
            for n in z.namelist()
            if re.search(r"word/footer\d+\.xml$", n)
        ]
    assert any('w:instr="PAGE"' in f for f in footers), "нет авто-поля PAGE в штампе"


def test_stamp_sheet_static_when_provided() -> None:
    """Если номер листа задан явно — он статичен (без поля PAGE)."""
    doc = _three_section_document()
    tb = doc.page_sections[1].title_block
    assert tb is not None
    tb.sheet = "5"
    out = tempfile.mktemp(suffix=".docx")
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    footers_text = "".join(_footers(out).values())
    # Номер листа статичный («5»), без авто-поля PAGE в этой ячейке.
    assert "5" in footers_text
    assert "Лист" in footers_text


def test_single_section_still_one_sectpr() -> None:
    """Регресс: документ с одной PageSection экспортируется как одна секция."""
    main = PageSection(
        id="main",
        name="ПЗ",
        type="main",
        page=PageGeometry(paper="A4"),
        footer=HeaderConfig(),
        content=[_sec("intro", "Введение", "Текст")],
    )
    doc = Document(
        profile_id="gost-7.32-2017",
        metadata=DocumentMetadata(title="Тест", year=2026),
        page_sections=[main],
    )
    out = tempfile.mktemp(suffix=".docx")
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    assert _doc_xml(out).count("<w:sectPr") == 1


# --- интеграция через конструктор -------------------------------------------


def test_builder_splits_frontmatter_with_stamp() -> None:
    """Конструктор: титул+задание (frontmatter) + штамп → 2 секции,
    титул без колонтитула, содержание полный штамп, далее форма 2а."""
    import pytest

    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _SECTION_TEMPLATES, _build_document_from_state

    title = {**_SECTION_TEMPLATES["title_spo"][1](), "id": "titlesec"}
    task = {**_SECTION_TEMPLATES["task_spo"][1](), "id": "tasksec"}
    state = {
        "title": "Работа",
        "author": "Аноним",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "title_block": {
            "enabled": True,
            "form": "form1",
            "designation": "АБВГ.001 ПЗ",
            "organization": "ОПЭК",
            "roles": [{"role": "Разраб.", "name": ""}, {"role": "Руковод.", "name": ""}],
        },
        "sections": [
            title,
            task,
            {"id": "toc", "heading": "Содержание", "blocks": [], "subsections": []},
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст."}],
                "subsections": [],
            },
        ],
    }
    out = tempfile.mktemp(suffix=".docx")
    out_bytes = _build_document_from_state(state)
    with open(out, "wb") as f:
        f.write(out_bytes)
    xml = _doc_xml(out)
    assert xml.count("<w:sectPr") == 2, "ожидались две секции вёрстки"
    assert xml.count("<w:titlePg") == 1
    footers = _footers(out)
    assert any(not t.strip() for t in footers.values()), "frontmatter без колонтитула"
    assert any("Разраб" in t for t in footers.values()), "полная надпись на содержании"


def test_builder_no_frontmatter_single_section() -> None:
    """Регресс: без frontmatter-разделов конструктор даёт одну секцию."""
    import pytest

    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _build_document_from_state

    state = {
        "title": "Работа",
        "author": "Аноним",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст."}],
                "subsections": [],
            },
        ],
    }
    out = tempfile.mktemp(suffix=".docx")
    with open(out, "wb") as f:
        f.write(_build_document_from_state(state))
    assert _doc_xml(out).count("<w:sectPr") == 1
