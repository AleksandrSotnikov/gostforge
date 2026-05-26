# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты межабзацных интервалов в стиле Normal.

По ГОСТ Р 2.105-2019 и ГОСТ 7.32-2017 разделение абзацев основного
текста достигается красной строкой и полуторным межстрочным
интервалом — дополнительные space_before/after между абзацами
должны быть 0. До исправления экспортёр наследовал Word-дефолт
'after=200 twips' (10 pt), и между абзацами вылезало лишнее белое
поле.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.profile import load_profile


def _docx_styles(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/styles.xml").decode("utf-8")


def _build_demo_bytes(tmp_path: Path, profile_id: str = "gost-7.32-2017") -> bytes:
    b = (
        work("X", year=2026)
        .section("Введение")
        .paragraph("первый абзац")
        .paragraph("второй абзац")
        .section("Список использованных источников")
        .reference("Кнут — М., 2007.")
    )
    out = tmp_path / "demo.docx"
    export_docx(b.build(), load_profile(profile_id), out)
    return out.read_bytes()


def test_normal_style_has_zero_spacing_by_default(tmp_path: Path) -> None:
    """В стиле Normal w:spacing w:before="0" w:after="0" — нет лишнего
    поля между абзацами."""
    data = _build_demo_bytes(tmp_path)
    styles = _docx_styles(data)
    # Найдём блок стиля Normal.
    block = re.search(r'styleId="Normal".*?</w:style>', styles, re.DOTALL)
    assert block is not None
    text = block.group(0)
    # w:spacing должен иметь w:before="0" и w:after="0".
    spacing_match = re.search(r"<w:spacing\b[^/]*/>", text)
    assert spacing_match, "w:spacing в Normal не найден"
    sp = spacing_match.group(0)
    assert 'w:before="0"' in sp, f"space_before не 0: {sp}"
    assert 'w:after="0"' in sp, f"space_after не 0: {sp}"


def test_normal_style_uses_profile_spacing(tmp_path: Path) -> None:
    """Если в профиле явно заданы 6 pt — экспортёр их пишет."""
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.styles.body.space_before_pt = 6
    profile.styles.body.space_after_pt = 6

    b = work("X", year=2026).section("Введение").paragraph("текст")
    out = tmp_path / "out.docx"
    export_docx(b.build(), profile, out)
    data = out.read_bytes()
    styles = _docx_styles(data)
    block = re.search(r'styleId="Normal".*?</w:style>', styles, re.DOTALL)
    sp = re.search(r"<w:spacing\b[^/]*/>", block.group(0)).group(0)
    # 6 pt = 120 twips.
    assert 'w:before="120"' in sp
    assert 'w:after="120"' in sp


def test_profile_body_defaults_are_gost_compliant() -> None:
    """gost-7.32-2017 и gost-r-2.105-2019: дефолт = 0 pt по обоим
    направлениям (как требует ГОСТ)."""
    for pid in ("gost-7.32-2017", "gost-r-2.105-2019"):
        p = load_profile(pid)
        assert p.styles.body.space_before_pt == 0, (
            f"{pid}: space_before должен быть 0, получено {p.styles.body.space_before_pt}"
        )
        assert p.styles.body.space_after_pt == 0


def test_style_override_applies_paragraph_spacing() -> None:
    """UI-override через _apply_style_overrides ставит body-spacing."""
    pytest.importorskip("streamlit")
    from gostforge.web.builder_editor import _apply_style_overrides

    p = load_profile("gost-7.32-2017")
    over = {"body_space_before_pt": 6, "body_space_after_pt": 4}
    new_p = _apply_style_overrides(p, over)
    assert new_p.styles.body.space_before_pt == 6
    assert new_p.styles.body.space_after_pt == 4
    # Оригинал не тронут.
    assert p.styles.body.space_before_pt == 0
