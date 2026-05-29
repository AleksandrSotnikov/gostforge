"""Тесты повторяющейся шапки таблицы (ГОСТ 7.32: «шапка повторяется при переносе»)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.profile import load_profile


def _docx_part(out: Path, part: str) -> str:
    with zipfile.ZipFile(out) as zf:
        return zf.read(part).decode("utf-8")


def test_table_header_row_has_tblheader_by_default(tmp_path: Path) -> None:
    """По умолчанию `repeat_header=True` → шапка получает `<w:tblHeader/>`."""
    b = (
        work("X", year=2026)
        .section("Глава 1")
        .table(headers=["A", "B"], rows=[["x", "y"], ["1", "2"]], caption="T1")
    )
    out = tmp_path / "tbl.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    document_xml = _docx_part(out, "word/document.xml")
    # tblHeader должен присутствовать (Word повторит шапку при переносе).
    assert "<w:tblHeader" in document_xml


def test_table_repeat_header_can_be_disabled(tmp_path: Path) -> None:
    """`repeat_header=False` + `continuation_caption=False` → `<w:tblHeader/>` не ставится."""
    profile = load_profile("gost-7.32-2017")
    profile.styles.table.repeat_header = False
    # continuation_caption тоже ставит tblHeader на свою строку — отключаем.
    profile.styles.table.continuation_caption = False
    b = work("X", year=2026).section("Глава").table(headers=["A"], rows=[["x"]], caption="T")
    out = tmp_path / "tbl.docx"
    export_docx(b.build(), profile, out)
    document_xml = _docx_part(out, "word/document.xml")
    assert "<w:tblHeader" not in document_xml


def test_continuation_caption_prepended_when_enabled(tmp_path: Path) -> None:
    """`continuation_caption=True` → первая строка таблицы — «Продолжение таблицы N»."""
    profile = load_profile("gost-7.32-2017")
    profile.styles.table.continuation_caption = True
    b = (
        work("X", year=2026)
        .section("Глава 1")
        .table(headers=["A", "B"], rows=[["x", "y"]], caption="T")
    )
    out = tmp_path / "tbl_cont.docx"
    export_docx(b.build(), profile, out)
    document_xml = _docx_part(out, "word/document.xml")
    assert "Продолжение таблицы 1" in document_xml


def test_continuation_caption_can_be_disabled(tmp_path: Path) -> None:
    """`continuation_caption=False` явно отключает строку «Продолжение таблицы N».

    Дефолт по ГОСТ 7.32 — `continuation_caption: true` (см. дефолтный
    профиль). Если кафедра не требует — отключается флагом в редакторе
    профиля.
    """
    profile = load_profile("gost-7.32-2017")
    profile.styles.table.continuation_caption = False
    b = work("X", year=2026).section("Глава 1").table(headers=["A"], rows=[["x"]], caption="T")
    out = tmp_path / "tbl_no_cont.docx"
    export_docx(b.build(), profile, out)
    document_xml = _docx_part(out, "word/document.xml")
    assert "Продолжение таблицы" not in document_xml


def test_continuation_caption_on_by_default(tmp_path: Path) -> None:
    """По умолчанию (ГОСТ 7.32) строка «Продолжение таблицы N» вставляется."""
    b = work("X", year=2026).section("Глава 1").table(headers=["A"], rows=[["x"]], caption="T")
    out = tmp_path / "tbl_cont.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    document_xml = _docx_part(out, "word/document.xml")
    assert "Продолжение таблицы 1" in document_xml


def test_continuation_row_uses_full_column_span(tmp_path: Path) -> None:
    """Строка «Продолжение...» должна занимать все колонки (gridSpan=N).

    После перехода на OOXML field code (IF/PAGE/PAGEREF) `.text` ячейки
    пустой — текст лежит в `<w:instrText>` поля, который Word оценивает
    при render-е. Поэтому проверяем gridSpan через сырое XML.
    """
    pytest.importorskip("docx")

    profile = load_profile("gost-7.32-2017")
    profile.styles.table.continuation_caption = True
    b = (
        work("X", year=2026)
        .section("Глава")
        .table(headers=["A", "B", "C"], rows=[["x", "y", "z"]], caption="T")
    )
    out = tmp_path / "span.docx"
    export_docx(b.build(), profile, out)
    document_xml = _docx_part(out, "word/document.xml")
    # Текст «Продолжение таблицы 1» лежит в instrText (field code).
    assert "Продолжение таблицы 1" in document_xml
    assert "<w:instrText" in document_xml
    # gridSpan=3 на первой ячейке таблицы (объединена по 3 колонкам).
    assert 'w:val="3"' in document_xml, "Ожидался <w:gridSpan w:val=\"3\"/>"
