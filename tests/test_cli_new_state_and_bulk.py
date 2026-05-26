# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты CLI new-state и bulk-операций / шаблонов разделов в UI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

# --- CLI new-state ---


@pytest.mark.parametrize("template", ["empty", "coursework", "thesis", "research_report"])
def test_new_state_creates_valid_json(tmp_path: Path, template: str) -> None:
    out_path = tmp_path / f"state_{template}.json"
    result = subprocess.run(
        [
            "gostforge",
            "new-state",
            "--template",
            template,
            "--title",
            f"Test {template}",
            "--year",
            "2026",
            "-o",
            str(out_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "sections" in data
    assert len(data["sections"]) >= 1
    assert data["title"] == f"Test {template}"
    assert data["year"] == 2026


def test_new_state_empty_template_has_intro_and_bib(tmp_path: Path) -> None:
    out_path = tmp_path / "state.json"
    subprocess.run(
        ["gostforge", "new-state", "--template", "empty", "-o", str(out_path)],
        check=True,
    )
    data = json.loads(out_path.read_text(encoding="utf-8"))
    headings = [s["heading"].lower() for s in data["sections"]]
    assert "введение" in headings
    assert any("список" in h for h in headings)


def test_new_state_with_profile_override(tmp_path: Path) -> None:
    out_path = tmp_path / "state.json"
    subprocess.run(
        [
            "gostforge",
            "new-state",
            "--template",
            "empty",
            "--profile",
            "gost-r-2.105-2019",
            "-o",
            str(out_path),
        ],
        check=True,
    )
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["profile_id"] == "gost-r-2.105-2019"


def test_new_state_then_generate_full_cycle(tmp_path: Path) -> None:
    """new-state → generate → валидный .docx."""
    state_path = tmp_path / "state.json"
    docx_path = tmp_path / "out.docx"

    r1 = subprocess.run(
        [
            "gostforge",
            "new-state",
            "--template",
            "coursework",
            "--title",
            "Цикл",
            "-o",
            str(state_path),
        ],
        capture_output=True,
        text=True,
    )
    assert r1.returncode == 0

    r2 = subprocess.run(
        ["gostforge", "generate", str(state_path), "-o", str(docx_path)],
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 0, f"stderr: {r2.stderr}"
    assert docx_path.exists()
    assert docx_path.stat().st_size > 1000


# --- Bulk-операции ---


pytest.importorskip("streamlit")

import streamlit as st  # noqa: E402

from gostforge.web.builder_editor import (  # noqa: E402
    _bulk_apply_title_case,
    _bulk_remove_empty_paragraphs,
    _bulk_reset_disabled_checks,
    _SECTION_TEMPLATES,
    _to_title_case,
)


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def test_bulk_remove_empty_paragraphs() -> None:
    state = {
        "sections": [
            {
                "heading": "A",
                "blocks": [
                    {"kind": "paragraph", "text": "real"},
                    {"kind": "paragraph", "text": ""},
                    {"kind": "paragraph", "text": "   "},
                    {"kind": "table", "headers": [], "rows": []},
                ],
            }
        ]
    }
    removed = _bulk_remove_empty_paragraphs(state)
    assert removed == 2
    blocks = state["sections"][0]["blocks"]
    assert len(blocks) == 2
    assert all((b.get("text") or "").strip() for b in blocks if b.get("kind") == "paragraph")


def test_bulk_remove_empty_in_subsections() -> None:
    state = {
        "sections": [
            {
                "heading": "A",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "A.1",
                        "blocks": [
                            {"kind": "paragraph", "text": ""},
                            {"kind": "paragraph", "text": "ok"},
                        ],
                    }
                ],
            }
        ]
    }
    removed = _bulk_remove_empty_paragraphs(state)
    assert removed == 1


def test_bulk_remove_handles_runs_format() -> None:
    """Параграфы в rich-формате (runs=[]) тоже считаются пустыми."""
    state = {
        "sections": [
            {
                "heading": "A",
                "blocks": [
                    {"kind": "paragraph", "runs": [{"kind": "text", "text": ""}]},
                    {"kind": "paragraph", "runs": [{"kind": "text", "text": "ok"}]},
                ],
            }
        ]
    }
    removed = _bulk_remove_empty_paragraphs(state)
    assert removed == 1


def test_to_title_case() -> None:
    assert _to_title_case("введение") == "Введение"
    assert _to_title_case("глава 1. анализ") == "Глава 1. Анализ"
    assert _to_title_case("") == ""
    assert _to_title_case("ABC") == "ABC"
    # Цифры и знаки не теряются.
    assert _to_title_case("1.1 подраздел") == "1.1 Подраздел"


def test_bulk_apply_title_case() -> None:
    state = {
        "sections": [
            {"heading": "введение", "blocks": []},
            {"heading": "Глава 1", "blocks": []},  # уже Title — не изменится
        ]
    }
    changed = _bulk_apply_title_case(state)
    assert changed == 1
    assert state["sections"][0]["heading"] == "Введение"


def test_bulk_reset_disabled_checks() -> None:
    state = {
        "sections": [
            {"heading": "X", "disabled_checks": ["*"]},
            {"heading": "Y", "disabled_checks": ["T.01"]},
            {"heading": "Z", "disabled_checks": []},
        ]
    }
    reset = _bulk_reset_disabled_checks(state)
    assert reset == 2
    for sec in state["sections"]:
        assert sec["disabled_checks"] == []


# --- Шаблоны разделов ---


def test_section_templates_factories_produce_valid_dicts() -> None:
    """Каждый шаблон возвращает dict с heading и blocks."""
    for key, (label, factory) in _SECTION_TEMPLATES.items():
        section = factory()
        assert isinstance(section, dict)
        assert "heading" in section
        assert "blocks" in section or "is_bibliography" in section


def test_chapter_template_has_subsection() -> None:
    """Шаблон главы имеет хотя бы один подраздел."""
    _, factory = _SECTION_TEMPLATES["chapter"]
    section = factory()
    assert section.get("subsections")
    assert len(section["subsections"]) >= 1


def test_appendix_template_skips_checks() -> None:
    """Шаблон приложения отключает проверки нормоконтроля."""
    _, factory = _SECTION_TEMPLATES["appendix"]
    section = factory()
    assert section.get("disabled_checks") == ["*"]


def test_bib_template_is_bibliography() -> None:
    _, factory = _SECTION_TEMPLATES["bib"]
    section = factory()
    assert section.get("is_bibliography") is True
    assert "references" in section
