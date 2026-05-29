"""Рендер основной надписи (штампа ЕСКД, ГОСТ 2.104) в нижний колонтитул.

Форма 1 — для заглавного листа; форма 2а — сокращённая для последующих.
Штамп строится таблицей в footer-е, поэтому повторяется на каждой
странице секции (как и любой колонтитул).

Компоновка граф приближена к ГОСТ 2.104 (ширина 185 мм, канонические
ширины колонок), но не претендует на пиксельную точность формы —
геометрия может уточняться. Содержательно покрыты основные графы:
1 (наименование), 2 (обозначение), 4 (литера), 5 (масса), 6 (масштаб),
7 (лист), 8 (листов), 9 (организация), 11/13 (фамилии/даты ролей).
"""

from __future__ import annotations

from typing import Any

from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt
from lxml import etree  # type: ignore[import-untyped]

from gostforge.model import TitleBlock

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Канонические ширины колонок формы 1 (мм), сумма = 185.
_FORM1_COLS_MM = [7, 10, 23, 15, 10, 14, 53, 53]
_FORM1_LABEL_PT = 8.0  # мелкий текст граф
_FORM1_TITLE_PT = 12.0  # наименование / обозначение


def _set_table_borders(table: Any) -> None:
    """Сплошные рамки 0.5 pt на все стороны и внутренние линии таблицы."""
    tbl = table._element
    tbl_pr = tbl.find(f"{{{W_NS}}}tblPr")
    if tbl_pr is None:
        tbl_pr = etree.SubElement(tbl, f"{{{W_NS}}}tblPr")
    existing = tbl_pr.find(f"{{{W_NS}}}tblBorders")
    if existing is not None:
        tbl_pr.remove(existing)
    borders = etree.SubElement(tbl_pr, f"{{{W_NS}}}tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = etree.SubElement(borders, f"{{{W_NS}}}{side}")
        el.set(f"{{{W_NS}}}val", "single")
        el.set(f"{{{W_NS}}}sz", "4")  # 0.5 pt
        el.set(f"{{{W_NS}}}space", "0")
        el.set(f"{{{W_NS}}}color", "auto")


def _set_cell(
    cell: Any,
    text: str,
    *,
    bold: bool = False,
    size_pt: float = _FORM1_LABEL_PT,
    align: str = "center",
) -> None:
    """Записать текст в ячейку штампа с нужным шрифтом/выравниванием.

    Вертикальное выравнивание — по центру; перезаписывает существующий
    единственный параграф ячейки, чтобы не плодить пустые строки.
    """
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    para = cell.paragraphs[0]
    para.alignment = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }.get(align, WD_ALIGN_PARAGRAPH.CENTER)
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(0)
    # Очищаем существующие run-ы.
    for run in list(para.runs):
        run._element.getparent().remove(run._element)
    run = para.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(size_pt)
    run.font.bold = bold


def _set_fixed_layout(table: Any, cols_mm: list[int]) -> None:
    """Зафиксировать ширины колонок (fixed layout, без автоподбора)."""
    table.autofit = False
    table.allow_autofit = False
    for i, width_mm in enumerate(cols_mm):
        for row in table.rows:
            row.cells[i].width = Mm(width_mm)


def _write_form1(footer: Any, tb: TitleBlock) -> Any:
    """Построить форму 1 (заглавный лист) — таблица 185×~ мм в footer-е."""
    table = footer.add_table(rows=7, cols=8, width=Mm(sum(_FORM1_COLS_MM)))
    table.alignment = WD_TABLE_ALIGNMENT.RIGHT
    _set_fixed_layout(table, _FORM1_COLS_MM)

    # Row 0 — обозначение документа (графа 2), на всю ширину.
    table.cell(0, 0).merge(table.cell(0, 7))
    _set_cell(table.cell(0, 0), tb.designation, bold=True, size_pt=_FORM1_TITLE_PT)

    # Row 1 — левый заголовок блока изменений (графы 14–18).
    for col, label in enumerate(("Изм.", "Лист", "№ докум.", "Подп.", "Дата")):
        _set_cell(table.cell(1, col), label)

    # Right — наименование (графа 1): объединяем строки 1–3, колонки 5–7.
    table.cell(1, 5).merge(table.cell(3, 7))
    _set_cell(table.cell(1, 5), tb.title, bold=True, size_pt=_FORM1_TITLE_PT)

    # Rows 2–6 — роли (графы 11/13). Слева: метка (c0+c1), фамилия (c2),
    # подпись (c3, пусто), дата (c4).
    roles = tb.roles[:5]
    for i in range(5):
        r = 2 + i
        table.cell(r, 0).merge(table.cell(r, 1))
        if i < len(roles):
            _set_cell(table.cell(r, 0), roles[i].role, align="left")
            _set_cell(table.cell(r, 2), roles[i].name)
            _set_cell(table.cell(r, 4), roles[i].date)
        else:
            _set_cell(table.cell(r, 0), "")

    # Row 4 справа — литера / масса / масштаб (графы 4/5/6).
    _set_cell(table.cell(4, 5), f"Лит. {tb.stage}".strip())
    _set_cell(table.cell(4, 6), f"Масса {tb.mass}".strip())
    _set_cell(table.cell(4, 7), f"М {tb.scale}".strip())

    # Row 5 справа — лист / листов (графы 7/8).
    _set_cell(table.cell(5, 5), f"Лист {tb.sheet}".strip())
    table.cell(5, 6).merge(table.cell(5, 7))
    _set_cell(table.cell(5, 6), f"Листов {tb.sheets_total}".strip())

    # Row 6 справа — организация (графа 9).
    table.cell(6, 5).merge(table.cell(6, 7))
    _set_cell(table.cell(6, 5), tb.organization, size_pt=_FORM1_LABEL_PT)

    _set_table_borders(table)
    return table


# Форма 2а — сокращённая (последующие листы): обозначение + номер листа.
_FORM2A_COLS_MM = [165, 20]


def _write_form2a(footer: Any, tb: TitleBlock) -> Any:
    """Построить форму 2а (последующие листы) — узкая таблица 185 мм."""
    table = footer.add_table(rows=1, cols=2, width=Mm(sum(_FORM2A_COLS_MM)))
    table.alignment = WD_TABLE_ALIGNMENT.RIGHT
    _set_fixed_layout(table, _FORM2A_COLS_MM)
    _set_cell(table.cell(0, 0), tb.designation, bold=True, align="left")
    _set_cell(table.cell(0, 1), f"Лист {tb.sheet}".strip())
    _set_table_borders(table)
    return table


def write_title_block(footer: Any, title_block: TitleBlock) -> Any | None:
    """Записать основную надпись в footer. Возвращает таблицу или None.

    Если штамп выключен (`enabled = False`) — ничего не пишет.
    """
    if not title_block.enabled:
        return None
    if title_block.form == "form2a":
        return _write_form2a(footer, title_block)
    return _write_form1(footer, title_block)
