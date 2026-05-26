# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты CLI export-md и helper-функции _state_to_markdown."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gostforge.cli import _block_to_md, _section_to_md, _state_to_markdown


# --- CLI ---


def test_export_md_creates_file(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = {
        "title": "Тест",
        "author": "И.И.",
        "year": 2026,
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст."}],
            }
        ],
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "out.md"
    result = subprocess.run(
        ["gostforge", "export-md", str(state_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    md = out_path.read_text(encoding="utf-8")
    assert "# Тест" in md
    assert "## Введение" in md
    assert "Текст." in md


def test_export_md_rejects_invalid_json(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("это не JSON", encoding="utf-8")
    out_path = tmp_path / "out.md"
    result = subprocess.run(
        ["gostforge", "export-md", str(bad_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


# --- _state_to_markdown ---


def test_title_metadata() -> None:
    state = {
        "title": "Курсовая",
        "author": "Иванов",
        "year": 2026,
        "supervisor": "Петров",
        "sections": [],
    }
    md = _state_to_markdown(state)
    assert "# Курсовая" in md
    assert "**Автор:** Иванов" in md
    assert "**Год:** 2026" in md
    assert "**Руководитель:** Петров" in md


def test_section_levels() -> None:
    state = {
        "title": "X",
        "sections": [
            {
                "heading": "Глава 1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "1.1 Подраздел",
                        "blocks": [],
                        "subsections": [
                            {"heading": "1.1.1 Пункт", "blocks": []}
                        ],
                    }
                ],
            }
        ],
    }
    md = _state_to_markdown(state)
    assert "## Глава 1" in md
    assert "### 1.1 Подраздел" in md
    assert "#### 1.1.1 Пункт" in md


def test_table_to_md() -> None:
    lines: list[str] = []
    _block_to_md(
        {
            "kind": "table",
            "headers": ["Параметр", "Значение"],
            "rows": [["Шрифт", "Times New Roman"]],
            "caption": "Параметры оформления",
        },
        lines=lines,
    )
    md = "\n".join(lines)
    assert "**Параметры оформления**" in md
    assert "| Параметр | Значение |" in md
    assert "|---|---|" in md
    assert "| Шрифт | Times New Roman |" in md


def test_list_ordered_and_unordered() -> None:
    lines: list[str] = []
    _block_to_md(
        {"kind": "list", "ordered": False, "items": ["a", "b"]},
        lines=lines,
    )
    lines.append("---")
    _block_to_md(
        {"kind": "list", "ordered": True, "items": ["шаг 1", "шаг 2"]},
        lines=lines,
    )
    md = "\n".join(lines)
    assert "- a" in md
    assert "- b" in md
    assert "1. шаг 1" in md
    assert "2. шаг 2" in md


def test_figure_to_md() -> None:
    lines: list[str] = []
    _block_to_md(
        {"kind": "figure", "image_path": "img.png", "caption": "Схема"},
        lines=lines,
    )
    md = "\n".join(lines)
    assert "![Схема](img.png)" in md


def test_figure_without_path_uses_italic_caption() -> None:
    lines: list[str] = []
    _block_to_md(
        {"kind": "figure", "image_path": "", "caption": "Схема"},
        lines=lines,
    )
    md = "\n".join(lines)
    assert "*Рисунок: Схема*" in md


def test_formula_to_md() -> None:
    lines: list[str] = []
    _block_to_md(
        {"kind": "formula", "latex": "x^2 + y^2 = z^2"},
        lines=lines,
    )
    md = "\n".join(lines)
    assert "$$ x^2 + y^2 = z^2 $$" in md


def test_bibliography_section() -> None:
    section = {
        "heading": "Список",
        "is_bibliography": True,
        "references": [
            "Кнут Д. — М., 2007.",
            "Кормен. — М., 2013.",
        ],
    }
    lines: list[str] = []
    _section_to_md(section, depth=2, lines=lines)
    md = "\n".join(lines)
    assert "1. Кнут" in md
    assert "2. Кормен" in md


def test_paragraph_with_runs() -> None:
    """Параграф в rich-формате (runs) сериализуется правильно."""
    lines: list[str] = []
    _block_to_md(
        {
            "kind": "paragraph",
            "runs": [
                {"kind": "text", "text": "Сначала "},
                {"kind": "text", "text": "и потом"},
            ],
        },
        lines=lines,
    )
    md = "\n".join(lines)
    assert "Сначала и потом" in md


def test_empty_paragraph_does_not_emit() -> None:
    """Пустой параграф не добавляет лишних строк."""
    lines: list[str] = []
    _block_to_md({"kind": "paragraph", "text": ""}, lines=lines)
    assert lines == []


def test_full_round_trip_new_state_to_md(tmp_path: Path) -> None:
    """new-state → export-md → валидный Markdown."""
    state_path = tmp_path / "state.json"
    md_path = tmp_path / "out.md"
    subprocess.run(
        [
            "gostforge", "new-state",
            "--template", "coursework",
            "--title", "Полный цикл",
            "-o", str(state_path),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["gostforge", "export-md", str(state_path), "-o", str(md_path)],
        check=True,
        capture_output=True,
    )
    md = md_path.read_text(encoding="utf-8")
    assert "# Полный цикл" in md
    # 4 раздела coursework → 4 ##.
    assert md.count("\n## ") == 4
