"""Тесты для группировки автоправок в веб-интерфейсе (вкладка «Автоисправление»)."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.fixer import FixApplied
from gostforge.model import Document, LogicalSection, PageGeometry, PageSection, TextRun
from gostforge.profile import load_profile
from gostforge.web.app import _build_fixed_docx_bytes, _group_fixes


def test_group_fixes_groups_by_code_and_counts() -> None:
    """Правки группируются по коду, считается количество, порядок описаний сохраняется."""
    fixes = [
        FixApplied(fixer_code="T.08", location="p1", description="двойной пробел №1"),
        FixApplied(fixer_code="F.01", location="s1", description="поля"),
        FixApplied(fixer_code="T.08", location="p2", description="двойной пробел №2"),
    ]
    groups = _group_fixes(fixes)
    # Сортировка по коду: F.01 раньше T.08.
    assert [code for code, _, _ in groups] == ["F.01", "T.08"]
    by_code = {code: (count, descs) for code, count, descs in groups}
    assert by_code["T.08"][0] == 2
    assert by_code["T.08"][1] == ["двойной пробел №1", "двойной пробел №2"]
    assert by_code["F.01"][0] == 1


def test_group_fixes_empty() -> None:
    """Пустой список правок → пустая группировка."""
    assert _group_fixes([]) == []


def test_build_fixed_docx_returns_applied_records() -> None:
    """`_build_fixed_docx_bytes` возвращает байты и список FixApplied с описаниями."""
    section = LogicalSection(
        id="s1",
        level=1,
        heading=[TextRun(text="ВВЕДЕНИЕ", font="Cambria", size_pt=16.0, bold=False)],
    )
    doc = Document()
    doc.page_sections.append(
        PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=PageGeometry(paper="A5"),
            content=[section],
        )
    )
    profile = load_profile("gost-7.32-2017")

    data, applied = _build_fixed_docx_bytes(doc, profile)
    assert data[:2] == b"PK"  # .docx — это zip
    codes = {fa.fixer_code for fa in applied}
    # Должны примениться и формат заголовка (H.01), и формат бумаги (F.02).
    assert "H.01" in codes
    assert "F.02" in codes
    assert all(fa.description for fa in applied), "у каждой правки есть описание"
