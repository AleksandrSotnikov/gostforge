"""Тесты соответствия списков диалогу Word «Изменение отступов в списке».

Проверяют связку модель ↔ OOXML:
* `marker_suffix` (tab/space/nothing) → `<w:suff w:val=...>`;
* `hanging_indent_cm` > 0 → `<w:ind w:hanging=...>` (маркер левее текста);
* `hanging_indent_cm` < 0 → `<w:ind w:firstLine=...>` (маркер правее текста).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from docx.shared import Cm

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.profile import load_profile
from gostforge.profile.schema import ListStyleProfile


def _numbering_xml(out: Path) -> str:
    with zipfile.ZipFile(out) as z:
        return z.read("word/numbering.xml").decode("utf-8")


def _our_lvl_ind(numbering: str, suff_val: str) -> str:
    """Найти <w:ind> внутри <w:lvl>, содержащего наш <w:suff w:val=...>.

    Шаблон python-docx уже содержит готовые abstractNum (с
    w:left=...,w:hanging=360, но БЕЗ w:suff) — поэтому ищем именно тот
    уровень, у которого есть наш suff, чтобы не зацепить дефолтные.
    """
    needle = f'<w:suff w:val="{suff_val}"/>'
    for lvl in re.findall(r"<w:lvl\b.*?</w:lvl>", numbering, flags=re.DOTALL):
        if needle in lvl:
            m = re.search(r"<w:ind\b[^>]*/>", lvl)
            assert m, "в нашем <w:lvl> не найден <w:ind>"
            return m.group(0)
    raise AssertionError(f"не найден <w:lvl> с {needle}")


def test_marker_right_of_text_uses_firstline(tmp_path: Path) -> None:
    """Положение маркера правее текста (text=0, маркер=1.25):
    hanging_indent_cm=-1.25 → suff=space + <w:ind w:firstLine=...> без hanging."""
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.styles.lists.marker_suffix = "space"
    profile.styles.lists.left_indent_cm = 0.0
    profile.styles.lists.hanging_indent_cm = -1.25

    b = work("X", year=2026).section("Введение").list(["один", "два"], ordered=False)
    out = tmp_path / "firstline.docx"
    export_docx(b.build(), profile, out)
    numbering = _numbering_xml(out)

    assert '<w:suff w:val="space"/>' in numbering
    expected_first = int(Cm(1.25).twips)
    # В нашем <w:lvl> есть <w:ind> с firstLine ≈ 709 twips и без hanging.
    first_ind = _our_lvl_ind(numbering, "space")
    assert f'w:firstLine="{expected_first}"' in first_ind
    assert "w:hanging=" not in first_ind


def test_marker_left_of_text_uses_hanging(tmp_path: Path) -> None:
    """Классический hanging-list (text=1.75, маркер=1.25 → hanging=0.5):
    suff=tab + <w:ind w:hanging=...>."""
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.styles.lists.marker_suffix = "tab"
    profile.styles.lists.left_indent_cm = 1.75
    profile.styles.lists.hanging_indent_cm = 0.5

    b = work("X", year=2026).section("Введение").list(["один", "два"], ordered=False)
    out = tmp_path / "hanging.docx"
    export_docx(b.build(), profile, out)
    numbering = _numbering_xml(out)

    assert '<w:suff w:val="tab"/>' in numbering
    expected_hanging = int(Cm(0.5).twips)
    # В нашем <w:lvl> есть <w:ind> с hanging ≈ 283 twips и без firstLine.
    first_ind = _our_lvl_ind(numbering, "tab")
    assert f'w:hanging="{expected_hanging}"' in first_ind
    assert "w:firstLine=" not in first_ind


def test_marker_suffix_field_defaults_and_values() -> None:
    """Поле marker_suffix: дефолт 'tab', принимает 'space'/'nothing'."""
    assert ListStyleProfile().marker_suffix == "tab"
    assert ListStyleProfile(marker_suffix="space").marker_suffix == "space"
    assert ListStyleProfile(marker_suffix="nothing").marker_suffix == "nothing"
