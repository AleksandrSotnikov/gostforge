"""Тесты CLI-команды `gostforge annotate`."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from docx import Document as DocxDocument

from gostforge.cli import main
from gostforge.model import Document, PageGeometry, PageSection


def _make_minimal_docx(path: Path) -> None:
    doc = DocxDocument()
    doc.add_paragraph("Тестовый абзац.")
    doc.save(str(path))


@pytest.fixture()
def bad_docx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "bad.docx"
    _make_minimal_docx(p)

    def fake_parse(_: object) -> Document:
        doc = Document()
        doc.page_sections.append(
            PageSection(
                id="main",
                name="Основная часть",
                type="main",
                page=PageGeometry(
                    margins_mm={"top": 25, "right": 15, "bottom": 20, "left": 30}
                ),
            )
        )
        return doc

    monkeypatch.setattr(
        "gostforge.annotator.docx_annotator.parse_docx", fake_parse
    )
    return p


def test_cli_annotate_creates_output(bad_docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.docx"
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["annotate", str(bad_docx), "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_cli_annotate_exit_code_zero(bad_docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.docx"
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["annotate", str(bad_docx), "-o", str(out)],
    )
    assert result.exit_code == 0


def test_cli_annotate_prints_count_message(bad_docx: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.docx"
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["annotate", str(bad_docx), "-o", str(out)],
    )
    assert "Создано пометок" in result.output
