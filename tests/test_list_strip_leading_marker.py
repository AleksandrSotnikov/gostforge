# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты автоматической очистки «вручную добавленного маркера» в
элементах списка перед записью numPr.

ПРОБЛЕМА. Пользователи часто вписывают в элемент списка уже
добавленный маркер: «- NET Framework 4.8», «– требование», «1. шаг».
Без очистки экспортёр-numPr рисует свой маркер ПЛЮС текстовый
остаётся — получаются «– – текст» или «1) 1. текст».
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.exporter.docx_exporter import _strip_leading_marker_from_inline
from gostforge.model import InlineFormula, TextRun
from gostforge.profile import load_profile


# --- _strip_leading_marker_from_inline (чистая функция) ---


@pytest.mark.parametrize(
    "input_text,expected",
    [
        # Bullet-маркеры с одиночным пробелом.
        ("- text", "text"),
        ("– text", "text"),
        ("— text", "text"),
        ("• text", "text"),
        ("* text", "text"),
        ("◦ text", "text"),
        # С табуляцией после маркера (как из вопроса пользователя).
        ("-\tNET Framework", "NET Framework"),
        ("–\tтекст", "текст"),
        # С множественными пробелами.
        ("-   text", "text"),
        ("–    text", "text"),
        # Смешанный Tab + пробелы.
        ("-\t  text", "text"),
        ("– \t text", "text"),
        # Ordered с точкой.
        ("1. шаг", "шаг"),
        ("12. длинный номер", "длинный номер"),
        # Ordered со скобкой.
        ("1) шаг", "шаг"),
        ("12) ещё", "ещё"),
        # Буквенная нумерация.
        ("а) пункт", "пункт"),
        ("a) item", "item"),
        ("A. ITEM", "ITEM"),
    ],
)
def test_strip_leading_marker_variants(input_text: str, expected: str) -> None:
    result = _strip_leading_marker_from_inline([TextRun(text=input_text)])
    assert result[0].text == expected


def test_strip_does_not_touch_text_without_marker() -> None:
    """Текст без маркера не должен меняться."""
    runs = [TextRun(text="обычный текст без маркера")]
    result = _strip_leading_marker_from_inline(runs)
    assert result[0].text == "обычный текст без маркера"


def test_strip_does_not_touch_dash_without_trailing_space() -> None:
    """«-100 рублей» — это число с минусом, не маркер. Не трогаем."""
    runs = [TextRun(text="-100 рублей")]
    result = _strip_leading_marker_from_inline(runs)
    assert result[0].text == "-100 рублей"


def test_strip_does_not_touch_marker_in_middle() -> None:
    """Маркер посреди текста не считается ведущим."""
    runs = [TextRun(text="текст – вставка – ещё")]
    result = _strip_leading_marker_from_inline(runs)
    assert result[0].text == "текст – вставка – ещё"


def test_strip_preserves_run_formatting() -> None:
    """Bold/italic/font у TextRun должны сохраниться после очистки."""
    runs = [TextRun(text="– жирный", bold=True, italic=True, font="Calibri")]
    result = _strip_leading_marker_from_inline(runs)
    assert result[0].text == "жирный"
    assert result[0].bold is True
    assert result[0].italic is True
    assert result[0].font == "Calibri"


def test_strip_only_first_run() -> None:
    """Маркер удаляется только из первого TextRun, не из остальных."""
    runs = [
        TextRun(text="– начало"),
        TextRun(text=", – продолжение"),  # дефис в начале второго рана — не трогаем
    ]
    result = _strip_leading_marker_from_inline(runs)
    assert result[0].text == "начало"
    assert result[1].text == ", – продолжение"


def test_strip_skip_non_textrun_at_start() -> None:
    """Если первый элемент не TextRun (например, InlineFormula),
    маркер не ищется и не удаляется."""
    runs = [
        InlineFormula(latex="x^2"),
        TextRun(text="– второй"),
    ]
    result = _strip_leading_marker_from_inline(runs)
    # Не должно меняться — мы не лезем глубже первого элемента.
    assert len(result) == 2
    second = result[1]
    assert isinstance(second, TextRun)
    assert second.text == "– второй"


def test_strip_empty_content() -> None:
    """Пустой content — no-op."""
    assert _strip_leading_marker_from_inline([]) == []


# --- Интеграция с экспортёром ---


def _docx_xml(out: Path, part: str) -> str:
    with zipfile.ZipFile(out) as zf:
        return zf.read(part).decode("utf-8")


def test_exported_list_has_no_duplicate_markers(tmp_path: Path) -> None:
    """Главный сценарий из вопроса пользователя: «- NET Framework 4.8».
    После экспорта в .docx не должно быть «-» в начале текста (только
    маркер от numPr)."""
    b = (
        work("X", year=2026)
        .section("Введение")
        .list(
            [
                "-\tNET Framework 4.8; SQL Server 2022 и выше.",
                "– второй пункт",
                "1) третий с цифрой",
            ],
            ordered=False,
        )
    )
    out = tmp_path / "no-dup.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    # В тексте не должно быть «-\t» или «- » в начале (после <w:t>).
    bad_starts = [
        '<w:t xml:space="preserve">-\t',
        '<w:t xml:space="preserve">- ',
        '<w:t xml:space="preserve">– ',
        '<w:t xml:space="preserve">1) ',
    ]
    for pattern in bad_starts:
        # Не должно быть в run-тексте параграфов списка.
        # Проверим что у нас есть текст «NET Framework» (без маркера).
        assert "NET Framework" in doc_xml
        if pattern in doc_xml:
            pytest.fail(
                f"Найден дубль-маркер в тексте: {pattern!r} — автоматическая очистка не сработала."
            )


def test_clean_text_appears_after_strip(tmp_path: Path) -> None:
    """После очистки текст элемента списка идёт без маркера."""
    b = work("X", year=2026).section("Введение").list(["-\tNET Framework 4.8"], ordered=False)
    out = tmp_path / "clean.docx"
    export_docx(b.build(), load_profile("gost-7.32-2017"), out)
    doc_xml = _docx_xml(out, "word/document.xml")
    assert "NET Framework 4.8" in doc_xml
    # Текст после <w:t>...</w:t> должен начинаться с «NET», не с «-».
    m = re.search(r"<w:t[^>]*>([^<]+)</w:t>", doc_xml)
    # Найдём run-текст параграфа списка с «NET Framework».
    runs = re.findall(r"<w:t[^>]*>([^<]+NET Framework[^<]*)</w:t>", doc_xml)
    for run_text in runs:
        assert not run_text.startswith("-"), f"Run-текст начинается с дефиса: {run_text!r}"
        assert not run_text.startswith("\t"), f"Run-текст начинается с таба: {run_text!r}"
