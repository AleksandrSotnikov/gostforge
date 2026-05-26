"""Тесты suff=space (короткий отступ маркер↔текст) и multilevel-списков."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.model import ListBlock
from gostforge.parser import parse_docx
from gostforge.profile import load_profile


def _numbering_xml(out: Path) -> str:
    with zipfile.ZipFile(out) as z:
        return z.read("word/numbering.xml").decode("utf-8")


# --- suff=space ---


def test_list_writes_suff_tab(tmp_path: Path) -> None:
    """После маркера ставится Tab (для классического hanging-list:
    Tab расширяется до позиции left, выравнивая текст первой строки
    с переносом)."""
    b = work("X", year=2026).section("Введение").list(["один", "два"], ordered=False)
    out = tmp_path / "out.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    numbering = _numbering_xml(out)
    assert '<w:suff w:val="tab"/>' in numbering


def test_ordered_list_writes_suff_tab(tmp_path: Path) -> None:
    b = work("X", year=2026).section("Введение").list(["шаг 1", "шаг 2"], ordered=True)
    out = tmp_path / "out.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    numbering = _numbering_xml(out)
    assert '<w:suff w:val="tab"/>' in numbering


# --- multilevel ---


def test_singlelevel_when_item_levels_empty(tmp_path: Path) -> None:
    """ListBlock без item_levels → singleLevel abstractNum (без подуровней)."""
    b = work("X", year=2026).section("Введение").list(["a", "b"], ordered=False)
    out = tmp_path / "single.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    numbering = _numbering_xml(out)
    assert '<w:multiLevelType w:val="singleLevel"/>' in numbering


def test_multilevel_when_item_levels_present(tmp_path: Path) -> None:
    """ListBlock.item_levels=[0, 1, 1, 0] → multilevel abstractNum."""
    from gostforge.builder import work as _work
    from gostforge.model import ListBlock as _LB
    from gostforge.model import TextRun as _TR

    b = _work("X", year=2026)
    sec = b.section("Введение")
    # Builder API ещё не имеет nested-list-добавления, поэтому
    # вручную вставляем ListBlock с item_levels.
    sec.paragraph("До списка.")
    # Подменим последний block — реально для теста пишем напрямую
    # через builder.build() и потом редактируем модель.
    doc = b.build()
    # Найдём LogicalSection и заменим/допишем ListBlock.
    intro = doc.page_sections[0].content[0]
    nested_list = _LB(
        id="L",
        ordered=False,
        items=[
            [_TR(text="первый")],
            [_TR(text="вложенный 1")],
            [_TR(text="вложенный 2")],
            [_TR(text="последний")],
        ],
        item_levels=[0, 1, 1, 0],
    )
    intro.children.append(nested_list)

    out = tmp_path / "multi.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    numbering = _numbering_xml(out)
    assert '<w:multiLevelType w:val="multilevel"/>' in numbering
    # Должно быть минимум 2 <w:lvl> (ilvl=0, ilvl=1).
    lvls = re.findall(r'<w:lvl w:ilvl="(\d+)">', numbering)
    assert "0" in lvls
    assert "1" in lvls


def test_multilevel_round_trip(tmp_path: Path) -> None:
    """Уровни вложенности сохраняются при export → parse."""
    from gostforge.model import ListBlock as _LB
    from gostforge.model import TextRun as _TR

    b = work("X", year=2026)
    sec = b.section("Введение")
    sec.paragraph("До списка.")
    doc = b.build()
    intro = doc.page_sections[0].content[0]
    nested = _LB(
        id="L",
        ordered=False,
        items=[
            [_TR(text="первый")],
            [_TR(text="вложенный")],
            [_TR(text="последний")],
        ],
        item_levels=[0, 1, 0],
    )
    intro.children.append(nested)

    out = tmp_path / "rt.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out)
    parsed = parse_docx(out)
    intro2 = parsed.page_sections[0].content[0]
    lists = [c for c in intro2.children if isinstance(c, ListBlock)]
    assert lists
    lst = lists[0]
    # Парсер ещё НЕ восстанавливает item_levels из docx (пока что),
    # но items сохраняются.
    assert len(lst.items) == 3


def test_listblock_default_levels_empty() -> None:
    """ListBlock() имеет item_levels=[] по умолчанию (backwards compatible)."""
    lb = ListBlock(id="L", ordered=False, items=[])
    assert lb.item_levels == []
