# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты CLI import-md и helper _markdown_to_state."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gostforge.cli import _markdown_to_state


def test_title_from_h1() -> None:
    md = "# Моя курсовая\n\nКакой-то текст.\n"
    state = _markdown_to_state(md)
    assert state["title"] == "Моя курсовая"


def test_title_override_via_argument() -> None:
    md = "# Из MD\n"
    state = _markdown_to_state(md, title="Из аргумента")
    assert state["title"] == "Из аргумента"


def test_top_level_sections_from_h2() -> None:
    md = "## Введение\n\n## Заключение\n"
    state = _markdown_to_state(md)
    headings = [s["heading"] for s in state["sections"]]
    assert headings == ["Введение", "Заключение"]


def test_subsection_h3() -> None:
    md = (
        "## Глава 1\n\n"
        "### 1.1 Подраздел\n\n"
        "### 1.2 Другой\n"
    )
    state = _markdown_to_state(md)
    chapter = state["sections"][0]
    assert len(chapter["subsections"]) == 2
    assert chapter["subsections"][0]["heading"] == "1.1 Подраздел"


def test_subsubsection_h4() -> None:
    md = (
        "## Глава 1\n"
        "### 1.1\n"
        "#### 1.1.1 Пункт\n"
    )
    state = _markdown_to_state(md)
    chapter = state["sections"][0]
    sub = chapter["subsections"][0]
    assert sub["subsections"][0]["heading"] == "1.1.1 Пункт"


def test_paragraph_in_section() -> None:
    md = "## Введение\n\nАктуальность темы.\n"
    state = _markdown_to_state(md)
    intro = state["sections"][0]
    para = next(b for b in intro["blocks"] if b["kind"] == "paragraph")
    assert para["text"] == "Актуальность темы."


def test_unordered_list() -> None:
    md = (
        "## Х\n"
        "- один\n"
        "- два\n"
        "- три\n"
    )
    state = _markdown_to_state(md)
    sec = state["sections"][0]
    lst = next(b for b in sec["blocks"] if b["kind"] == "list")
    assert lst["ordered"] is False
    assert lst["items"] == ["один", "два", "три"]


def test_ordered_list() -> None:
    md = (
        "## Х\n"
        "1. шаг 1\n"
        "2. шаг 2\n"
    )
    state = _markdown_to_state(md)
    sec = state["sections"][0]
    lst = next(b for b in sec["blocks"] if b["kind"] == "list")
    assert lst["ordered"] is True
    assert lst["items"] == ["шаг 1", "шаг 2"]


def test_gfm_table() -> None:
    md = (
        "## Х\n"
        "| Параметр | Значение |\n"
        "|---|---|\n"
        "| Шрифт | TNR |\n"
        "| Кегль | 14 |\n"
    )
    state = _markdown_to_state(md)
    sec = state["sections"][0]
    tbl = next(b for b in sec["blocks"] if b["kind"] == "table")
    assert tbl["headers"] == ["Параметр", "Значение"]
    assert tbl["rows"] == [["Шрифт", "TNR"], ["Кегль", "14"]]


def test_formula() -> None:
    md = "## Х\n$$ a^2 + b^2 = c^2 $$\n"
    state = _markdown_to_state(md)
    sec = state["sections"][0]
    f = next(b for b in sec["blocks"] if b["kind"] == "formula")
    assert f["latex"] == "a^2 + b^2 = c^2"


def test_figure_image() -> None:
    md = "## Х\n![Архитектура](arch.png)\n"
    state = _markdown_to_state(md)
    sec = state["sections"][0]
    fig = next(b for b in sec["blocks"] if b["kind"] == "figure")
    assert fig["image_path"] == "arch.png"
    assert fig["caption"] == "Архитектура"


def test_bibliography_detected_and_refs_populated() -> None:
    md = (
        "## Список использованных источников\n\n"
        "1. Кнут Д. — М., 2007.\n"
        "2. Кормен. — М., 2013.\n"
    )
    state = _markdown_to_state(md)
    bib = state["sections"][0]
    assert bib.get("is_bibliography") is True
    assert bib["references"] == ["Кнут Д. — М., 2007.", "Кормен. — М., 2013."]


def test_full_cycle_export_then_import(tmp_path: Path) -> None:
    """state → export-md → import-md → state с теми же разделами."""
    state_in = {
        "title": "Полный цикл",
        "author": "И.И.",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Актуальность."}],
            },
            {
                "heading": "Глава 1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "1.1",
                        "blocks": [{"kind": "paragraph", "text": "текст 1.1"}],
                    }
                ],
            },
            {
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "references": ["Кнут. — М., 2007."],
            },
        ],
    }
    state_path = tmp_path / "in.json"
    md_path = tmp_path / "mid.md"
    out_state_path = tmp_path / "out.json"

    state_path.write_text(
        json.dumps(state_in, ensure_ascii=False), encoding="utf-8"
    )
    subprocess.run(
        ["gostforge", "export-md", str(state_path), "-o", str(md_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["gostforge", "import-md", str(md_path), "-o", str(out_state_path)],
        check=True,
        capture_output=True,
    )
    state_out = json.loads(out_state_path.read_text(encoding="utf-8"))
    assert state_out["title"] == "Полный цикл"
    headings_in = [s["heading"] for s in state_in["sections"]]
    headings_out = [s["heading"] for s in state_out["sections"]]
    assert headings_in == headings_out
    # bibliography сохранилась.
    bib = next(s for s in state_out["sections"] if s.get("is_bibliography"))
    assert "Кнут" in bib["references"][0]


def test_cli_import_md_smoke(tmp_path: Path) -> None:
    """gostforge import-md как процесс."""
    md_path = tmp_path / "in.md"
    md_path.write_text("# Заголовок\n\n## Введение\n\nТекст.\n", encoding="utf-8")
    out_path = tmp_path / "out.json"
    result = subprocess.run(
        ["gostforge", "import-md", str(md_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["title"] == "Заголовок"
    assert len(data["sections"]) == 1
    assert data["sections"][0]["heading"] == "Введение"
