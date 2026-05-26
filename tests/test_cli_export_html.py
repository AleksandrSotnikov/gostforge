"""Тесты CLI export-html и helper-функций."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gostforge.cli import (
    _block_to_html,
    _paragraph_to_html_inline,
    _section_to_html,
    _state_to_html,
)

# --- CLI ---


def test_export_html_creates_standalone(tmp_path: Path) -> None:
    state = {
        "title": "Тест",
        "year": 2026,
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст."}],
            }
        ],
    }
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    op = tmp_path / "o.html"
    r = subprocess.run(
        ["gostforge", "export-html", str(sp), "-o", str(op)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    html = op.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "<title>Тест</title>" in html
    assert "Times New Roman" in html  # CSS
    assert "Введение" in html
    assert "<p>Текст.</p>" in html


def test_export_html_fragment_mode(tmp_path: Path) -> None:
    state = {"title": "X", "sections": [{"heading": "А", "blocks": []}]}
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    op = tmp_path / "o.html"
    r = subprocess.run(
        ["gostforge", "export-html", str(sp), "-o", str(op), "--fragment"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    html = op.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" not in html
    assert "<body>" not in html  # fragment
    assert "А" in html  # heading


def test_export_html_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("не JSON", encoding="utf-8")
    r = subprocess.run(
        ["gostforge", "export-html", str(bad), "-o", str(tmp_path / "x.html")],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0


# --- _state_to_html ---


def test_html_escapes_special_chars() -> None:
    state = {
        "title": "<script>alert(1)</script>",
        "sections": [{"heading": "<b>заголовок</b>", "blocks": []}],
    }
    html = _state_to_html(state, standalone=True)
    # HTML-инъекции должны быть экранированы.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_html_levels_h1_h2_h3() -> None:
    state = {
        "title": "T",
        "sections": [
            {
                "heading": "Глава 1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "1.1 Подраздел",
                        "blocks": [],
                        "subsections": [
                            {
                                "heading": "1.1.1 Пункт",
                                "blocks": [],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    html = _state_to_html(state, standalone=True)
    assert "<h1>T</h1>" in html
    assert "<h2>Глава 1</h2>" in html
    assert "<h3>1.1 Подраздел</h3>" in html
    assert "<h4>1.1.1 Пункт</h4>" in html


# --- _block_to_html ---


def test_block_paragraph_simple() -> None:
    parts: list[str] = []
    _block_to_html({"kind": "paragraph", "text": "Hello world"}, parts=parts)
    html = "\n".join(parts)
    assert "<p>Hello world</p>" in html


def test_block_paragraph_with_runs() -> None:
    parts: list[str] = []
    _block_to_html(
        {
            "kind": "paragraph",
            "runs": [
                {"kind": "text", "text": "До "},
                {"kind": "text", "text": "жирно", "bold": True},
                {"kind": "text", "text": " и "},
                {"kind": "text", "text": "курсив", "italic": True},
            ],
        },
        parts=parts,
    )
    html = "\n".join(parts)
    assert "<strong>жирно</strong>" in html
    assert "<em>курсив</em>" in html


def test_block_paragraph_with_bold_italic() -> None:
    parts: list[str] = []
    _block_to_html(
        {
            "kind": "paragraph",
            "runs": [{"kind": "text", "text": "оба", "bold": True, "italic": True}],
        },
        parts=parts,
    )
    html = "\n".join(parts)
    assert "<strong><em>оба</em></strong>" in html


def test_block_list_unordered() -> None:
    parts: list[str] = []
    _block_to_html(
        {"kind": "list", "ordered": False, "items": ["один", "два"]},
        parts=parts,
    )
    html = "\n".join(parts)
    assert "<ul>" in html
    assert "<li>один</li>" in html
    assert "<li>два</li>" in html


def test_block_list_ordered() -> None:
    parts: list[str] = []
    _block_to_html(
        {"kind": "list", "ordered": True, "items": ["шаг 1", "шаг 2"]},
        parts=parts,
    )
    html = "\n".join(parts)
    assert "<ol>" in html


def test_block_table() -> None:
    parts: list[str] = []
    _block_to_html(
        {
            "kind": "table",
            "headers": ["A", "B"],
            "rows": [["1", "2"]],
            "caption": "Параметры",
        },
        parts=parts,
    )
    html = "\n".join(parts)
    assert "<table>" in html
    assert "<caption>Параметры</caption>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_block_figure() -> None:
    parts: list[str] = []
    _block_to_html(
        {"kind": "figure", "image_path": "fig.png", "caption": "Схема"},
        parts=parts,
    )
    html = "\n".join(parts)
    assert "<figure>" in html
    assert '<img src="fig.png"' in html
    assert "<figcaption>Схема</figcaption>" in html


def test_block_formula() -> None:
    parts: list[str] = []
    _block_to_html(
        {"kind": "formula", "latex": "x^2 + y^2 = z^2"},
        parts=parts,
    )
    html = "\n".join(parts)
    assert '<div class="formula">' in html
    assert "x^2 + y^2 = z^2" in html


def test_bibliography_section() -> None:
    parts: list[str] = []
    _section_to_html(
        {
            "heading": "Список",
            "is_bibliography": True,
            "references": ["Кнут — М., 2007.", "Кормен — М., 2013."],
        },
        depth=2,
        parts=parts,
    )
    html = "\n".join(parts)
    assert '<ol class="bibliography">' in html
    assert "Кнут" in html
    assert "Кормен" in html


def test_full_cycle_new_state_to_html(tmp_path: Path) -> None:
    """new-state → export-html → валидный standalone HTML."""
    sp = tmp_path / "s.json"
    op = tmp_path / "o.html"
    subprocess.run(
        [
            "gostforge",
            "new-state",
            "--template",
            "coursework",
            "--title",
            "Полный цикл",
            "-o",
            str(sp),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["gostforge", "export-html", str(sp), "-o", str(op)],
        check=True,
        capture_output=True,
    )
    html = op.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "Полный цикл" in html


def test_paragraph_with_runs_inline() -> None:
    text = _paragraph_to_html_inline({"kind": "paragraph", "runs": [{"kind": "text", "text": "X"}]})
    assert text == "X"


def test_paragraph_with_formula_in_runs() -> None:
    text = _paragraph_to_html_inline(
        {
            "kind": "paragraph",
            "runs": [
                {"kind": "text", "text": "Формула "},
                {"kind": "formula", "latex": "x^2"},
            ],
        }
    )
    assert "\\(x^2\\)" in text


def test_paragraph_with_citation_in_runs() -> None:
    text = _paragraph_to_html_inline(
        {
            "kind": "paragraph",
            "runs": [
                {"kind": "text", "text": "См. "},
                {"kind": "citation", "source_id": "1", "pages": "42"},
            ],
        }
    )
    assert "[1, с. 42]" in text
