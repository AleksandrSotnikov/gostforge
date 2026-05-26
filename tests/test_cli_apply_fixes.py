"""Тесты CLI apply-fixes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_apply_fixes_double_spaces(tmp_path: Path) -> None:
    """T.08 фикс убирает двойные пробелы."""
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Текст с  двойными  пробелами."}],
            },
            {
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "references": ["Кнут. — М., 2007."],
            },
        ],
    }
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(
        [
            "gostforge",
            "apply-fixes",
            str(in_path),
            "-o",
            str(out_path),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out_state = json.loads(out_path.read_text(encoding="utf-8"))
    intro = next(s for s in out_state["sections"] if "введ" in s["heading"].lower())
    p_text = ""
    for b in intro["blocks"]:
        if b.get("kind") == "paragraph":
            t = b.get("text", "")
            if not t and b.get("runs"):
                t = "".join(r.get("text", "") for r in b["runs"] if r.get("kind") == "text")
            p_text += t
    assert "  " not in p_text, f"Двойные пробелы остались: {p_text!r}"


def test_apply_fixes_with_only_filter(tmp_path: Path) -> None:
    """--only T.08 применяет ТОЛЬКО T.08, не другие фиксеры."""
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "С  двойными - дефисами."}],
            },
            {
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "references": ["Кнут. — М., 2007."],
            },
        ],
    }
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(
        [
            "gostforge",
            "apply-fixes",
            str(in_path),
            "-o",
            str(out_path),
            "--only",
            "T.08",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    # В stdout указан только T.08, нет T.11 (em-dash).
    assert "T.08" in r.stdout
    assert "T.11" not in r.stdout


def test_apply_fixes_no_violations(tmp_path: Path) -> None:
    """state без исправимых нарушений → 0 фиксов, не падает."""
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [
            {
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": "Идеальный текст."}],
            },
            {
                "heading": "Список использованных источников",
                "is_bibliography": True,
                "references": ["Кнут Д. — М. : Вильямс, 2007. — 832 с."],
            },
        ],
    }
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    r = subprocess.run(
        ["gostforge", "apply-fixes", str(in_path), "-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert out_path.exists()


def test_apply_fixes_rejects_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("это не JSON", encoding="utf-8")
    out = tmp_path / "out.json"
    r = subprocess.run(
        ["gostforge", "apply-fixes", str(bad), "-o", str(out)],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0


def test_apply_fixes_preserves_profile_id(tmp_path: Path) -> None:
    state = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-r-2.105-2019",
        "sections": [{"heading": "Введение", "blocks": []}],
    }
    in_path = tmp_path / "in.json"
    out_path = tmp_path / "out.json"
    in_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        ["gostforge", "apply-fixes", str(in_path), "-o", str(out_path)],
        check=True,
        capture_output=True,
    )
    out_state = json.loads(out_path.read_text(encoding="utf-8"))
    assert out_state["profile_id"] == "gost-r-2.105-2019"
