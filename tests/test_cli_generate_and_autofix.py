# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты CLI команды generate и кнопки «Применить автофиксы» в UI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


# --- CLI: gostforge generate ---


def test_generate_creates_docx_from_state(tmp_path: Path) -> None:
    """gostforge generate state.json -o out.docx — собирает docx."""
    state = {
        "title": "Тест",
        "author": "И.И.",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст."}],
            },
            {
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "references": ["Кнут. — М., 2007."],
            },
        ],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "out.docx"

    result = subprocess.run(
        ["gostforge", "generate", str(state_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert out_path.exists()
    assert out_path.stat().st_size > 1000  # настоящий docx, не пустой


def test_generate_rejects_invalid_json(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("это не JSON", encoding="utf-8")
    out_path = tmp_path / "out.docx"

    result = subprocess.run(
        ["gostforge", "generate", str(bad_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "JSON" in result.stderr


def test_generate_rejects_state_without_sections(tmp_path: Path) -> None:
    state_path = tmp_path / "empty.json"
    state_path.write_text(json.dumps({"title": "X"}), encoding="utf-8")
    out_path = tmp_path / "out.docx"

    result = subprocess.run(
        ["gostforge", "generate", str(state_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "sections" in result.stderr


def test_generate_profile_override(tmp_path: Path) -> None:
    """--profile переопределяет state['profile_id']."""
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "p"}],
            }
        ],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "out.docx"

    result = subprocess.run(
        [
            "gostforge", "generate", str(state_path),
            "-o", str(out_path),
            "--profile", "gost-r-2.105-2019",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert out_path.exists()


def test_full_cli_cycle_import_then_generate(tmp_path: Path) -> None:
    """End-to-end: docx → import-docx → generate → новый docx."""
    from gostforge.builder import work
    from gostforge.exporter import export_docx
    from gostforge.profile import load_profile

    # Шаг 0: оригинальный docx.
    b = (
        work("Цикл", author="A", year=2025)
        .section("Введение").paragraph("текст один")
        .section("Список использованных источников").reference("Кнут. — М., 2007.")
    )
    doc = b.build()
    out1 = tmp_path / "step1.docx"
    export_docx(doc, load_profile("gost-7.32-2017"), out1)

    # Шаг 1: import-docx.
    state_path = tmp_path / "state.json"
    result = subprocess.run(
        ["gostforge", "import-docx", str(out1), "-o", str(state_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"import-docx failed: {result.stderr}"
    assert state_path.exists()

    # Шаг 2: generate из state.
    out2 = tmp_path / "step2.docx"
    result = subprocess.run(
        ["gostforge", "generate", str(state_path), "-o", str(out2)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"generate failed: {result.stderr}"
    assert out2.exists()
    assert out2.stat().st_size > 1000


# --- UI: _apply_autofixes_to_state ---


pytest.importorskip("streamlit")

import streamlit as st  # noqa: E402

from gostforge.web.builder_editor import (  # noqa: E402
    _apply_autofixes_to_state,
)


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def test_apply_autofixes_with_no_state_returns_silently() -> None:
    """Без builder_state ничего не падает."""
    _apply_autofixes_to_state()  # просто не должно бросить
    # session_state остаётся пустым
    assert "builder_state" not in st.session_state


def test_apply_autofixes_with_fixable_violations() -> None:
    """Документ с двойными пробелами (T.08) → autofix их убирает."""
    # T.08 — known fixable (двойные пробелы).
    st.session_state["builder_state"] = {
        "title": "Тест",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [
                    {
                        "kind": "paragraph",
                        # Двойной пробел между словами — T.08.
                        "text": "Текст  с  двойными  пробелами.",
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
    _apply_autofixes_to_state()
    # После autofix двойных пробелов в первом параграфе быть не должно.
    intro = st.session_state["builder_state"]["sections"][0]
    paragraphs = [b for b in intro["blocks"] if b.get("kind") == "paragraph"]
    for p in paragraphs:
        text = p.get("text", "")
        if not text and p.get("runs"):
            text = "".join(
                r.get("text", "")
                for r in p["runs"]
                if r.get("kind") == "text"
            )
        assert "  " not in text, f"Двойные пробелы остались: {text!r}"


def test_apply_autofixes_updates_summary() -> None:
    """После применения autofix last_import_summary должен показать
    меньше нарушений и пометить applied_fixes."""
    st.session_state["builder_state"] = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [
                    {"kind": "paragraph", "text": "Двойные  пробелы  тут."}
                ],
            },
            {
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "references": ["Кнут. — М., 2007."],
            },
        ],
    }
    st.session_state["last_import_summary"] = {
        "filename": "old.docx",
        "sections_count": 2,
        "total": 10,
        "by_severity": {"error": 10, "warning": 0, "info": 0},
        "top_codes": [{"code": "T.08", "count": 3}],
    }
    _apply_autofixes_to_state()
    new_summary = st.session_state.get("last_import_summary", {})
    # applied_fixes выставлен — autofix хотя бы что-то сделал.
    assert new_summary.get("applied_fixes", 0) >= 1
