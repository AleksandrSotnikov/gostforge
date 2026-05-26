# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты импорта PDF в state-конструктора.

Эвристика заголовков (`_looks_like_heading`) тестируется напрямую и
не требует pdfplumber. Полный путь `import_pdf_to_state` проверяется
через подменённый (fake) модуль pdfplumber, чтобы тесты не зависели
от опциональной зависимости.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from gostforge.pdf_importer import (
    PdfImportError,
    _looks_like_heading,
    import_pdf_to_state,
)


class TestLooksLikeHeading:
    def test_structural_heading(self) -> None:
        ok, level = _looks_like_heading("Введение")
        assert ok
        assert level == 1

    def test_structural_heading_case_insensitive(self) -> None:
        ok, level = _looks_like_heading("ЗАКЛЮЧЕНИЕ")
        assert ok
        assert level == 1

    def test_appendix_prefix(self) -> None:
        ok, level = _looks_like_heading("Приложение А")
        assert ok
        assert level == 1

    def test_numbered_level_1(self) -> None:
        ok, level = _looks_like_heading("1 Анализ предметной области")
        assert ok
        assert level == 1

    def test_numbered_level_2(self) -> None:
        ok, level = _looks_like_heading("1.1 Постановка задачи")
        assert ok
        assert level == 2

    def test_numbered_level_3(self) -> None:
        ok, level = _looks_like_heading("1.1.1 Детализация")
        assert ok
        assert level == 3

    def test_numbered_deep_capped_at_3(self) -> None:
        ok, level = _looks_like_heading("1.1.1.1 Очень глубоко")
        assert ok
        assert level == 3

    def test_uppercase_short(self) -> None:
        ok, level = _looks_like_heading("ОБЗОР ЛИТЕРАТУРЫ")
        assert ok
        assert level == 1

    def test_normal_sentence_not_heading(self) -> None:
        ok, _ = _looks_like_heading("Это обычное предложение, которое заканчивается точкой.")
        assert not ok

    def test_too_long_not_heading(self) -> None:
        ok, _ = _looks_like_heading("Слово " * 30)
        assert not ok

    def test_empty_not_heading(self) -> None:
        ok, _ = _looks_like_heading("   ")
        assert not ok

    def test_uppercase_with_trailing_dot_not_heading(self) -> None:
        ok, _ = _looks_like_heading("ВАЖНО.")
        assert not ok


def _install_fake_pdfplumber(monkeypatch: pytest.MonkeyPatch, pages_text: list[str]) -> None:
    """Подменить pdfplumber фейком, возвращающим заданные страницы."""

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePdf:
        def __init__(self) -> None:
            self.pages = [_FakePage(t) for t in pages_text]

        def __enter__(self) -> _FakePdf:
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

    def _open(_path: str) -> _FakePdf:
        return _FakePdf()

    fake = SimpleNamespace(open=_open)
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)


class TestImportPdfToState:
    def test_file_not_found(self, tmp_path: Any) -> None:
        with pytest.raises(FileNotFoundError):
            import_pdf_to_state(tmp_path / "missing.pdf")

    def test_missing_pdfplumber_raises(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 stub")
        # Делаем `import pdfplumber` неуспешным.
        monkeypatch.setitem(sys.modules, "pdfplumber", None)
        with pytest.raises(PdfImportError):
            import_pdf_to_state(pdf)

    def test_basic_structure(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_pdfplumber(
            monkeypatch,
            [
                "Введение\n"
                "Актуальность работы обусловлена ростом данных.\n"
                "1 Анализ предметной области\n"
                "В этом разделе рассмотрены подходы.\n"
            ],
        )
        pdf = tmp_path / "work.pdf"
        pdf.write_bytes(b"%PDF-1.4 stub")
        state = import_pdf_to_state(pdf, profile_id="gost-7.32-2017")

        assert state["profile_id"] == "gost-7.32-2017"
        assert state["title"] == "work"
        headings = [s["heading"] for s in state["sections"]]
        assert headings == ["Введение", "1 Анализ предметной области"]
        intro = state["sections"][0]
        assert intro["blocks"][0]["kind"] == "paragraph"
        assert "Актуальность" in intro["blocks"][0]["text"]

    def test_text_before_heading_becomes_intro(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_pdfplumber(
            monkeypatch,
            ["Просто текст без заголовка в начале документа тут.\n"],
        )
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF stub")
        state = import_pdf_to_state(pdf)
        assert state["sections"][0]["heading"] == "Введение"
        assert "Просто текст" in state["sections"][0]["blocks"][0]["text"]

    def test_bibliography_section(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_pdfplumber(
            monkeypatch,
            [
                "Список использованных источников\n"
                "1. Иванов И.И. Базы данных. — М.: Наука, 2007.\n"
                "2. Петров П.П. Алгоритмы. — СПб.: Питер, 2010.\n"
            ],
        )
        pdf = tmp_path / "b.pdf"
        pdf.write_bytes(b"%PDF stub")
        state = import_pdf_to_state(pdf)
        bib = state["sections"][0]
        assert bib.get("is_bibliography") is True
        assert len(bib["references"]) == 2
        assert bib["references"][0].startswith("1. Иванов")

    def test_explicit_title_overrides_filename(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_pdfplumber(monkeypatch, ["Введение\nТекст.\n"])
        pdf = tmp_path / "raw.pdf"
        pdf.write_bytes(b"%PDF stub")
        state = import_pdf_to_state(pdf, title="Моя ВКР")
        assert state["title"] == "Моя ВКР"

    def test_unreadable_pdf_raises_import_error(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(_path: str) -> Any:
            raise ValueError("битый PDF")

        fake = SimpleNamespace(open=_boom)
        monkeypatch.setitem(sys.modules, "pdfplumber", fake)
        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"not really a pdf")
        with pytest.raises(PdfImportError):
            import_pdf_to_state(pdf)
