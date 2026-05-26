"""Тесты rich-Markdown round-trip: bold/italic в runs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gostforge.cli import _paragraph_to_md, _parse_md_inline

# --- _paragraph_to_md ---


def test_paragraph_simple_text() -> None:
    block = {"kind": "paragraph", "text": "обычный текст"}
    assert _paragraph_to_md(block) == "обычный текст"


def test_paragraph_with_bold_run() -> None:
    block = {
        "kind": "paragraph",
        "runs": [
            {"kind": "text", "text": "Простой "},
            {"kind": "text", "text": "жирный", "bold": True},
        ],
    }
    assert _paragraph_to_md(block) == "Простой **жирный**"


def test_paragraph_with_italic_run() -> None:
    block = {
        "kind": "paragraph",
        "runs": [{"kind": "text", "text": "курсив", "italic": True}],
    }
    assert _paragraph_to_md(block) == "*курсив*"


def test_paragraph_with_bold_italic() -> None:
    block = {
        "kind": "paragraph",
        "runs": [{"kind": "text", "text": "оба", "bold": True, "italic": True}],
    }
    assert _paragraph_to_md(block) == "***оба***"


def test_paragraph_with_inline_formula_in_runs() -> None:
    block = {
        "kind": "paragraph",
        "runs": [
            {"kind": "text", "text": "Формула "},
            {"kind": "formula", "latex": "x^2"},
        ],
    }
    assert "$x^2$" in _paragraph_to_md(block)


def test_paragraph_with_citation() -> None:
    block = {
        "kind": "paragraph",
        "runs": [
            {"kind": "text", "text": "См. "},
            {"kind": "citation", "source_id": "1", "pages": "42"},
        ],
    }
    md = _paragraph_to_md(block)
    assert "[1, с. 42]" in md


def test_paragraph_with_xref_uses_placeholder() -> None:
    block = {
        "kind": "paragraph",
        "runs": [
            {"kind": "text", "text": "Текст "},
            {"kind": "xref", "target_id": "fig1", "prefix": "см. рис."},
        ],
    }
    md = _paragraph_to_md(block)
    assert "см. рис.[→fig1]" in md


# --- _parse_md_inline ---


def test_parse_plain_text() -> None:
    runs = _parse_md_inline("обычный текст")
    assert runs == [{"kind": "text", "text": "обычный текст"}]


def test_parse_bold() -> None:
    runs = _parse_md_inline("До **жирного** после")
    assert runs == [
        {"kind": "text", "text": "До "},
        {"kind": "text", "text": "жирного", "bold": True},
        {"kind": "text", "text": " после"},
    ]


def test_parse_italic_star() -> None:
    runs = _parse_md_inline("Это *курсив*")
    assert any(r.get("italic") for r in runs)


def test_parse_italic_underscore() -> None:
    runs = _parse_md_inline("Это _курсив_")
    assert any(r.get("italic") for r in runs)


def test_parse_bold_italic() -> None:
    runs = _parse_md_inline("***оба***")
    assert runs[0].get("bold") is True
    assert runs[0].get("italic") is True


def test_parse_mixed() -> None:
    runs = _parse_md_inline("Простой **жирный** и *курсив*")
    assert len(runs) == 4
    # Жирный, курсив, plain — по очереди.
    bolds = [r for r in runs if r.get("bold")]
    italics = [r for r in runs if r.get("italic")]
    assert len(bolds) == 1
    assert len(italics) == 1


# --- Round-trip через CLI ---


def test_export_import_md_preserves_bold(tmp_path: Path) -> None:
    """state с bold-run экспортируется и импортируется обратно
    с сохранением форматирования."""
    state_in = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "runs": [
                            {"kind": "text", "text": "Cлово "},
                            {"kind": "text", "text": "жирное", "bold": True},
                            {"kind": "text", "text": " дальше"},
                        ],
                    }
                ],
            }
        ],
    }
    state_path = tmp_path / "in.json"
    md_path = tmp_path / "mid.md"
    out_path = tmp_path / "out.json"

    state_path.write_text(json.dumps(state_in, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        ["gostforge", "export-md", str(state_path), "-o", str(md_path)],
        check=True,
        capture_output=True,
    )
    md = md_path.read_text(encoding="utf-8")
    assert "**жирное**" in md

    subprocess.run(
        ["gostforge", "import-md", str(md_path), "-o", str(out_path)],
        check=True,
        capture_output=True,
    )
    state_out = json.loads(out_path.read_text(encoding="utf-8"))
    intro = state_out["sections"][0]
    para = next(b for b in intro["blocks"] if b.get("kind") == "paragraph")
    assert "runs" in para
    bold_runs = [r for r in para["runs"] if r.get("bold")]
    assert any(r.get("text") == "жирное" for r in bold_runs)
