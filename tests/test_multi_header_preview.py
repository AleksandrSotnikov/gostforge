"""Тесты HTML-превью многоуровневой шапки таблицы.

Превью отображается в редакторе таблицы после поля «Доп. шапка», чтобы
пользователь сразу видел, как auto-merges сработают в финале.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _build_multi_header_preview_html


def test_preview_empty_when_no_extra_rows() -> None:
    """Если extra_rows пуст — превью не генерируется (одноуровневая шапка)."""
    html = _build_multi_header_preview_html(
        extra_rows=[],
        headers=["A", "B"],
        merges=[],
    )
    assert html == ""


def test_preview_renders_two_level_header_with_colspan() -> None:
    """Двухуровневая шапка: «Группа 1» (colspan=2) | «Группа 2» (colspan=2)."""
    html = _build_multi_header_preview_html(
        extra_rows=[["Группа 1", "", "Группа 2", ""]],
        headers=["A", "B", "C", "D"],
        merges=[
            {"row": 0, "col": 0, "rowspan": 1, "colspan": 2},
            {"row": 0, "col": 2, "rowspan": 1, "colspan": 2},
        ],
    )
    # Главная проверка — colspan=2 присутствует для обеих групп.
    assert html.count('colspan="2"') == 2
    # Группы есть.
    assert "Группа 1" in html
    assert "Группа 2" in html
    # Подзаголовки есть.
    assert ">A<" in html
    assert ">D<" in html


def test_preview_skips_consumed_cells() -> None:
    """Ячейки внутри colspan не рисуются дважды."""
    html = _build_multi_header_preview_html(
        extra_rows=[["X", ""]],
        headers=["a", "b"],
        merges=[{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}],
    )
    # «X» отрисован один раз, пустая ячейка не отрисована.
    assert html.count(">X<") == 1
    # Не должно быть пустой <th>&nbsp;</th> в первой строке —
    # она «съедена» colspan-ом.
    # В первой строке должна быть всего одна th-ячейка.
    first_row = html.split("</tr>")[0]
    assert first_row.count("<th") == 1


def test_preview_includes_data_sample_when_provided() -> None:
    """Если data_sample передан — добавлен в превью как обычная (не header) строка."""
    html = _build_multi_header_preview_html(
        extra_rows=[["Группа", ""]],
        headers=["A", "B"],
        merges=[{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}],
        data_sample=["x1", "y1"],
    )
    assert "x1" in html and "y1" in html
    # Sample-строка рисуется через <td>, а шапка через <th>.
    assert "<td " in html


def test_preview_escapes_html() -> None:
    """HTML-special символы в названиях экранируются (защита от XSS-like)."""
    html = _build_multi_header_preview_html(
        extra_rows=[["<script>", ""]],
        headers=["a", "b"],
        merges=[{"row": 0, "col": 0, "rowspan": 1, "colspan": 2}],
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
