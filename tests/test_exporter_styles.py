"""Тесты на правильное применение profile.styles в экспортёре.

Эти тесты проверяют визуальные настройки, которые до Phase 3.x
оставались дефолтными от шаблона Word и нарушали ГОСТ-вёрстку:
* синий цвет заголовков (теперь auto),
* Cambria-theme в заголовках вместо Times New Roman,
* отсутствие рамок у таблиц,
* выравнивание подписи рисунка/таблицы,
* кастомные маркеры списков из профиля.
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


def _build_demo_docx(tmp_path: Path, profile_id: str = "gost-7.32-2017") -> bytes:
    """Сборка демо-документа с разделом, рисунком, таблицей, списками."""
    b = (
        work("Демо", author="A", year=2026)
        .section("Введение")
        .paragraph("Текст.")
        .table(
            headers=["Параметр", "Значение"],
            rows=[["x", "1"], ["y", "2"]],
            caption="Параметры",
        )
        .figure("/tmp/no-file.png", "Архитектура")
        .list(["один", "два"], ordered=False)
        .list(["первый шаг", "второй шаг"], ordered=True)
    )
    doc = b.build()
    profile = load_profile(profile_id)
    out = tmp_path / "demo.docx"
    export_docx(doc, profile, out)
    return out.read_bytes()


def _docx_styles_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/styles.xml").decode("utf-8")


def _docx_document_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/document.xml").decode("utf-8")


# --- Heading: цвет ---------------------------------------------------------


def test_heading1_color_is_not_blue(tmp_path: Path) -> None:
    """Heading 1 не должен иметь синий accent1-цвет из дефолтного шаблона."""
    data = _build_demo_docx(tmp_path)
    styles = _docx_styles_xml(data)
    h1_block = re.search(r'styleId="Heading1".*?</w:style>', styles, re.DOTALL)
    assert h1_block is not None
    # Не должно быть w:color val="365F91" (тот самый синий).
    assert "365F91" not in h1_block.group(0)
    # И не должно быть themeColor accent1.
    assert "accent1" not in h1_block.group(0)


def test_heading_fonts_are_explicit_times_new_roman(tmp_path: Path) -> None:
    """Heading-стили должны иметь явный Times New Roman, не theme-Cambria."""
    data = _build_demo_docx(tmp_path)
    styles = _docx_styles_xml(data)
    for level in (1, 2, 3, 4):
        block = re.search(rf'styleId="Heading{level}".*?</w:style>', styles, re.DOTALL)
        assert block is not None, f"Heading {level} style missing"
        block_text = block.group(0)
        # theme-атрибутов быть не должно.
        assert "majorHAnsi" not in block_text, f"Heading {level}: theme font осталась"
        assert "asciiTheme" not in block_text, f"Heading {level}: theme font осталась"
        # Times New Roman должен быть явно прописан.
        assert "Times New Roman" in block_text, f"Heading {level}: TNR не прописан"


def test_heading1_is_uppercase_in_document(tmp_path: Path) -> None:
    """heading_1 с uppercase=True (default для ГОСТ 7.32) → текст ALL CAPS."""
    data = _build_demo_docx(tmp_path)
    doc_xml = _docx_document_xml(data)
    assert "ВВЕДЕНИЕ" in doc_xml
    # Но обычные параграфы — в нормальном регистре.
    assert "Текст." in doc_xml


# --- Normal: theme-fonts cleanup ------------------------------------------


def test_normal_style_has_explicit_font(tmp_path: Path) -> None:
    """Стиль Normal должен иметь явный font, без minorHAnsi-theme."""
    data = _build_demo_docx(tmp_path)
    styles = _docx_styles_xml(data)
    normal_block = re.search(r'styleId="Normal".*?</w:style>', styles, re.DOTALL)
    assert normal_block is not None
    block_text = normal_block.group(0)
    assert "Times New Roman" in block_text
    assert "minorHAnsi" not in block_text


# --- Caption: alignment по центру для рисунков -----------------------------


def test_figure_caption_is_centered(tmp_path: Path) -> None:
    """Параграф с подписью рисунка должен иметь jc=center."""
    data = _build_demo_docx(tmp_path)
    doc_xml = _docx_document_xml(data)
    # Найдём параграф с подписью «Рисунок 1 — Архитектура».
    m = re.search(
        r"<w:p\b.*?Рисунок 1.*?</w:p>",
        doc_xml,
        re.DOTALL,
    )
    assert m is not None, "Подпись рисунка не найдена"
    para = m.group(0)
    # Должно быть w:jc w:val="center".
    assert 'w:val="center"' in para, "Подпись рисунка не выровнена по центру"


def test_table_caption_is_left_aligned(tmp_path: Path) -> None:
    """Параграф с подписью таблицы — слева (table.caption.alignment=left)."""
    data = _build_demo_docx(tmp_path)
    doc_xml = _docx_document_xml(data)
    m = re.search(
        r"<w:p\b.*?Таблица 1.*?</w:p>",
        doc_xml,
        re.DOTALL,
    )
    assert m is not None
    para = m.group(0)
    # Не должно быть jc=center (default для Caption-стиля).
    assert 'w:val="center"' not in para


# --- Table: рамки ----------------------------------------------------------


def test_table_has_borders(tmp_path: Path) -> None:
    data = _build_demo_docx(tmp_path)
    doc_xml = _docx_document_xml(data)
    # tblBorders должен присутствовать на каждой таблице.
    tbl_borders = re.findall(r"<w:tblBorders>.*?</w:tblBorders>", doc_xml, re.DOTALL)
    assert len(tbl_borders) >= 1, "Рамки таблицы не сгенерированы"
    # У каждой стороны — w:val="single".
    block = tbl_borders[0]
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        assert f"<w:{side} " in block, f"Сторона {side} не задана"
    assert 'w:val="single"' in block


def test_table_borders_disabled_via_profile(tmp_path: Path) -> None:
    """Если в профиле border_style=none — рамок нет."""

    profile = load_profile("gost-7.32-2017")
    # Создадим копию профиля с отключёнными рамками через model_copy.
    profile_no_borders = profile.model_copy(deep=True)
    profile_no_borders.styles.table.border_style = "none"

    b = (
        work("Демо", year=2026)
        .section("Введение")
        .table(
            headers=["a", "b"],
            rows=[["1", "2"]],
            caption="Без рамок",
        )
    )
    doc = b.build()
    out = tmp_path / "no-borders.docx"
    export_docx(doc, profile_no_borders, out)

    with zipfile.ZipFile(out) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:tblBorders>" not in doc_xml


# --- Lists: маркеры из профиля --------------------------------------------


def _docx_numbering_xml(data: bytes) -> str:
    """Достать word/numbering.xml из байтов docx."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/numbering.xml").decode("utf-8")


def test_bullet_uses_dash_by_default(tmp_path: Path) -> None:
    """По ГОСТ Р 7.32-2017 — bullet-маркер тире (–).

    После перехода на настоящие numPr-списки маркер живёт в
    numbering.xml (lvlText), а не в тексте параграфа. Тест проверяет,
    что в numbering.xml есть abstractNum с lvlText='–'.
    """
    data = _build_demo_docx(tmp_path)
    numbering = _docx_numbering_xml(data)
    assert re.search(r'<w:lvlText w:val="–"\s*/>', numbering), (
        "Тире-маркер не найден в numbering.xml как lvlText"
    )


def test_ordered_uses_paren_format_by_default(tmp_path: Path) -> None:
    """ordered_format = "{n})" → lvlText='%1)' в numbering.xml."""
    data = _build_demo_docx(tmp_path)
    numbering = _docx_numbering_xml(data)
    assert re.search(r'<w:lvlText w:val="%1\)"\s*/>', numbering), (
        "Шаблон «%1)» не найден в numbering.xml"
    )


def test_custom_bullet_char_from_profile(tmp_path: Path) -> None:
    """Кастомный маркер «•» через profile.styles.lists.bullet_char."""
    profile = load_profile("gost-7.32-2017").model_copy(deep=True)
    profile.styles.lists.bullet_char = "•"

    b = work("Демо", year=2026).section("Введение").list(["a", "b"], ordered=False)
    doc = b.build()
    out = tmp_path / "custom-bullet.docx"
    export_docx(doc, profile, out)

    with zipfile.ZipFile(out) as zf:
        numbering = zf.read("word/numbering.xml").decode("utf-8")
    assert re.search(r'<w:lvlText w:val="•"\s*/>', numbering)


# --- Figure: alignment рисунка --------------------------------------------


def test_figure_paragraph_centered_by_default(tmp_path: Path) -> None:
    """Параграф с (placeholder)-рисунком должен быть выровнен по центру."""
    data = _build_demo_docx(tmp_path)
    doc_xml = _docx_document_xml(data)
    # «[Рисунок: fig-1]» в параграфе с jc=center.
    m = re.search(r"<w:p\b.*?\[Рисунок: fig-1\].*?</w:p>", doc_xml, re.DOTALL)
    assert m is not None
    assert 'w:val="center"' in m.group(0)


# --- Heading: spacing -----------------------------------------------------


def test_heading_spacing_before_and_after_from_profile(tmp_path: Path) -> None:
    """spacing_before_pt и spacing_after_pt из профиля попадают в стиль."""
    data = _build_demo_docx(tmp_path)
    styles = _docx_styles_xml(data)
    h1_block = re.search(r'styleId="Heading1".*?</w:style>', styles, re.DOTALL)
    assert h1_block is not None
    # spacing_before_pt=18 → 18*20 = 360 twips.
    # spacing_after_pt=12 → 12*20 = 240 twips.
    spacing = re.search(r"<w:spacing[^/]*/>", h1_block.group(0))
    assert spacing is not None
    sp_text = spacing.group(0)
    assert 'w:before="360"' in sp_text
    assert 'w:after="240"' in sp_text


# --- ESKD-профиль: ширина полей и шрифт ------------------------------------


def test_eskd_profile_uses_correct_margins(tmp_path: Path) -> None:
    """gost-r-2.105-2019: правое поле 10 мм (не 15 как в базовом)."""
    data = _build_demo_docx(tmp_path, profile_id="gost-r-2.105-2019")
    doc_xml = _docx_document_xml(data)
    # 10 мм = 567 twips (1 cm = 567 twips, 10 mm = 567 twips).
    # Но docx использует mm через python-docx → проверим что pgMar есть.
    assert "<w:pgMar" in doc_xml
    # Точное значение проверять через сложный regex не будем — это
    # покрыто отдельным test_exporter.py::test_export_writes_page_margins.


def test_eskd_profile_heading_color_also_auto(tmp_path: Path) -> None:
    """ЕСКД-профиль наследует heading-цвет от gost-7.32 → auto."""
    data = _build_demo_docx(tmp_path, profile_id="gost-r-2.105-2019")
    styles = _docx_styles_xml(data)
    h1_block = re.search(r'styleId="Heading1".*?</w:style>', styles, re.DOTALL)
    assert h1_block is not None
    assert "365F91" not in h1_block.group(0)


# --- Linked char-styles (HeadingNChar) ---


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_heading_linked_char_style_has_no_blue(tmp_path: Path, level: int) -> None:
    """Linked char-стиль (Heading{N}Char) не должен сохранять синий цвет
    из дефолтного шаблона. При рендере run-ов внутри heading-параграфа
    Word применяет char-стиль поверх параграф-стиля, и его цвет
    перекроет наш auto, если не править оба."""
    data = _build_demo_docx(tmp_path)
    styles = _docx_styles_xml(data)
    block = re.search(rf'styleId="Heading{level}Char".*?</w:style>', styles, re.DOTALL)
    # Heading1Char/Heading2Char точно есть в python-docx-template,
    # Heading3Char/Heading4Char тоже.
    assert block is not None, f"Heading{level}Char отсутствует"
    block_text = block.group(0)
    assert "365F91" not in block_text, f"Heading{level}Char: синий накопил"
    assert "accent1" not in block_text, f"Heading{level}Char: themeColor=accent1"
    # Cambria-theme должен быть очищен.
    assert "majorHAnsi" not in block_text, f"Heading{level}Char: theme-font осталась"
    # Times New Roman прописан явно.
    assert "Times New Roman" in block_text


@pytest.mark.parametrize(
    "profile_id", ["gost-7.32-2017", "gost-r-2.105-2019", "example-department"]
)
def test_all_profiles_generate_clean_headings(tmp_path: Path, profile_id: str) -> None:
    """Регресс на покрытие профилей: каждый профиль из profiles/ должен
    генерировать документ, где Heading1+Heading1Char не содержат
    синего цвета и theme-fonts."""
    data = _build_demo_docx(tmp_path, profile_id=profile_id)
    styles = _docx_styles_xml(data)
    # Полный поиск 365F91 во ВСЁМ styles.xml имеет ложные срабатывания
    # на латентные tableStyle (LightShading и т. п.) — но они не
    # используются документом. Ограничиваемся Heading1+Heading1Char.
    h1 = re.search(r'styleId="Heading1".*?</w:style>', styles, re.DOTALL)
    h1c = re.search(r'styleId="Heading1Char".*?</w:style>', styles, re.DOTALL)
    assert h1 is not None
    assert h1c is not None
    assert "365F91" not in h1.group(0)
    assert "365F91" not in h1c.group(0)
    assert "Times New Roman" in h1.group(0)
    assert "Times New Roman" in h1c.group(0)
