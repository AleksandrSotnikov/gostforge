"""Тесты CLI diff-state и helper _state_diff_summary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gostforge.cli import _compare_sections, _state_diff_summary

# --- _state_diff_summary ---


def test_identical_states_no_diff() -> None:
    state = {
        "title": "X",
        "sections": [{"heading": "Введение", "blocks": [{"kind": "paragraph", "text": "T"}]}],
    }
    out = _state_diff_summary(state, state)
    assert not any(out.values())


def test_title_changed_detected() -> None:
    a = {"title": "A", "sections": []}
    b = {"title": "B", "sections": []}
    out = _state_diff_summary(a, b)
    assert out["title_changed"] is True


def test_section_added() -> None:
    a = {"title": "X", "sections": [{"heading": "Введение", "blocks": []}]}
    b = {
        "title": "X",
        "sections": [
            {"heading": "Введение", "blocks": []},
            {"heading": "Заключение", "blocks": []},
        ],
    }
    out = _state_diff_summary(a, b)
    assert out["sections_added"] == ["Заключение"]
    assert out["sections_removed"] == []


def test_section_removed() -> None:
    a = {
        "title": "X",
        "sections": [
            {"heading": "Введение", "blocks": []},
            {"heading": "Заключение", "blocks": []},
        ],
    }
    b = {"title": "X", "sections": [{"heading": "Введение", "blocks": []}]}
    out = _state_diff_summary(a, b)
    assert out["sections_removed"] == ["Заключение"]
    assert out["sections_added"] == []


def test_section_modified_blocks() -> None:
    a = {
        "title": "X",
        "sections": [{"heading": "Введение", "blocks": []}],
    }
    b = {
        "title": "X",
        "sections": [{"heading": "Введение", "blocks": [{"kind": "paragraph", "text": "p"}]}],
    }
    out = _state_diff_summary(a, b)
    assert len(out["sections_modified"]) == 1
    assert "блоков" in out["sections_modified"][0]["summary"]


# --- _compare_sections ---


def test_compare_identical_returns_empty() -> None:
    sec = {"heading": "X", "blocks": [], "subsections": []}
    assert _compare_sections(sec, sec) == ""


def test_compare_block_count() -> None:
    a = {"blocks": []}
    b = {"blocks": [{"kind": "paragraph", "text": "t"}]}
    assert "блоков 0→1" in _compare_sections(a, b)


def test_compare_disabled_checks() -> None:
    a = {"disabled_checks": []}
    b = {"disabled_checks": ["T.01"]}
    assert "disabled_checks" in _compare_sections(a, b)


def test_compare_references() -> None:
    a = {"references": ["ref1"]}
    b = {"references": ["ref1", "ref2"]}
    assert "источников 1→2" in _compare_sections(a, b)


def test_compare_subsections_count() -> None:
    a = {"subsections": []}
    b = {"subsections": [{"heading": "X", "blocks": []}]}
    assert "подразделов 0→1" in _compare_sections(a, b)


# --- CLI ---


def test_cli_diff_state_summary_mode(tmp_path: Path) -> None:
    a = {
        "title": "A",
        "sections": [{"heading": "Введение", "blocks": []}],
    }
    b = {
        "title": "B",
        "sections": [
            {"heading": "Введение", "blocks": [{"kind": "paragraph", "text": "p"}]},
            {"heading": "Заключение", "blocks": []},
        ],
    }
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    a_path.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    b_path.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(
        ["gostforge", "diff-state", str(a_path), str(b_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "Заголовок изменён" in r.stdout
    assert "Добавлено разделов: 1" in r.stdout
    assert "Заключение" in r.stdout


def test_cli_diff_state_unified_mode(tmp_path: Path) -> None:
    a = {"title": "A", "sections": []}
    b = {"title": "B", "sections": []}
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    a_path.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    b_path.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(
        [
            "gostforge",
            "diff-state",
            str(a_path),
            str(b_path),
            "--mode",
            "unified",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    # Unified diff содержит «-/+» строки и заголовки --- / +++.
    assert "---" in r.stdout
    assert "+++" in r.stdout
    assert '"A"' in r.stdout
    assert '"B"' in r.stdout


def test_cli_diff_state_identical(tmp_path: Path) -> None:
    """Идентичные state → 'Без изменений.'"""
    state = {"title": "X", "sections": []}
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    p1.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    p2.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(
        ["gostforge", "diff-state", str(p1), str(p2)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "Без изменений" in r.stdout
