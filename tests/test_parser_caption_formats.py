"""Тесты распознавания разных форматов подписей рисунков и таблиц.

Проверяем, что парсер извлекает числовой `number` из подписи в формах,
встречающихся в реальных документах: с точкой/двоеточием/тире как
разделителем, с многоуровневой нумерацией, с нумерацией приложений
(«А.1») и с неразрывными пробелами (NBSP, ``\\xa0``).
"""

from __future__ import annotations

from pathlib import Path

from gostforge.model import Figure, Table
from gostforge.parser.docx_parser import parse_docx

from .conftest import make_docx


def _first_figure(path: Path) -> Figure:
    """Достать первый Figure из распарсенного документа (упростить ассерты)."""
    doc = parse_docx(path)
    figures = [b for ps in doc.page_sections for b in ps.content if isinstance(b, Figure)]
    assert len(figures) == 1, f"Ожидался один Figure, получено {len(figures)}"
    return figures[0]


def _first_table(path: Path) -> Table:
    """Достать первый Table из распарсенного документа."""
    doc = parse_docx(path)
    tables = [b for ps in doc.page_sections for b in ps.content if isinstance(b, Table)]
    assert len(tables) == 1, f"Ожидался один Table, получено {len(tables)}"
    return tables[0]


def test_figure_caption_default_em_dash(tmp_path: Path) -> None:
    """«Рисунок 1 — Foo»: дефолтная форма с em-dash — number=1."""
    path = make_docx(
        tmp_path / "fig_emdash.docx",
        figures=[{"caption": "Рисунок 1 — Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_figure_caption_with_period(tmp_path: Path) -> None:
    """«Рисунок 1. Foo»: разделитель — точка (ГОСТ Р 2.105) — number=1."""
    path = make_docx(
        tmp_path / "fig_period.docx",
        figures=[{"caption": "Рисунок 1. Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_figure_caption_with_colon(tmp_path: Path) -> None:
    """«Рисунок 1: Foo»: разделитель — двоеточие — number=1."""
    path = make_docx(
        tmp_path / "fig_colon.docx",
        figures=[{"caption": "Рисунок 1: Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_figure_caption_multilevel_number(tmp_path: Path) -> None:
    """«Рисунок 1.2 — Foo»: многоуровневая нумерация — берём верхний уровень (1)."""
    path = make_docx(
        tmp_path / "fig_multilevel.docx",
        figures=[{"caption": "Рисунок 1.2 — Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_figure_caption_appendix_number(tmp_path: Path) -> None:
    """«Рисунок А.1 — Foo»: нумерация приложений — берём числовую часть (1)."""
    path = make_docx(
        tmp_path / "fig_appendix.docx",
        figures=[{"caption": "Рисунок А.1 — Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_figure_caption_with_nbsp(tmp_path: Path) -> None:
    """NBSP вместо обычных пробелов: «Рисунок\\xa01\\xa0—\\xa0Foo» — number=1."""
    path = make_docx(
        tmp_path / "fig_nbsp.docx",
        figures=[{"caption": "Рисунок\xa01\xa0—\xa0Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_figure_caption_with_en_dash(tmp_path: Path) -> None:
    """«Рисунок 1 – Foo»: en-dash как разделитель — number=1."""
    path = make_docx(
        tmp_path / "fig_endash.docx",
        figures=[{"caption": "Рисунок 1 – Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_figure_caption_with_hyphen(tmp_path: Path) -> None:
    """«Рисунок 1 - Foo»: обычный дефис-минус как разделитель — number=1."""
    path = make_docx(
        tmp_path / "fig_hyphen.docx",
        figures=[{"caption": "Рисунок 1 - Схема алгоритма"}],
    )
    assert _first_figure(path).number == 1


def test_table_caption_with_period(tmp_path: Path) -> None:
    """«Таблица 1. Foo»: разделитель — точка — number=1."""
    path = make_docx(
        tmp_path / "tbl_period.docx",
        tables=[
            {
                "caption": "Таблица 1. Результаты эксперимента",
                "headers": ["A", "B"],
                "rows": [["1", "2"]],
            }
        ],
    )
    assert _first_table(path).number == 1


def test_table_caption_appendix_number(tmp_path: Path) -> None:
    """«Таблица Б.2 — Foo»: нумерация приложений у таблицы — number=2."""
    path = make_docx(
        tmp_path / "tbl_appendix.docx",
        tables=[
            {
                "caption": "Таблица Б.2 — Результаты эксперимента",
                "headers": ["A", "B"],
                "rows": [["1", "2"]],
            }
        ],
    )
    assert _first_table(path).number == 2


def test_table_caption_multilevel_and_nbsp(tmp_path: Path) -> None:
    """«Таблица 3.4 — Foo» c NBSP-разделителями — number=3."""
    path = make_docx(
        tmp_path / "tbl_multilevel_nbsp.docx",
        tables=[
            {
                "caption": "Таблица\xa03.4\xa0—\xa0Результаты эксперимента",
                "headers": ["A", "B"],
                "rows": [["1", "2"]],
            }
        ],
    )
    assert _first_table(path).number == 3


def test_figure_without_caption_has_no_number(tmp_path: Path) -> None:
    """Рисунок без подписи: number остаётся None (back-compat)."""
    path = make_docx(
        tmp_path / "fig_no_caption.docx",
        figures=[{}],
    )
    assert _first_figure(path).number is None
