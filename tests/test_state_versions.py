"""Тесты версионирования state и live-preview одного раздела."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import streamlit as st


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


# --- Сохранение версий state ---


def test_save_state_version_creates_file(tmp_path: Path, monkeypatch) -> None:
    from gostforge.web import builder_editor

    monkeypatch.setattr(builder_editor, "_state_versions_dir", lambda: tmp_path)
    state = {
        "title": "Курсовая работа",
        "year": 2026,
        "profile_id": "gost-7.32-2017",
        "sections": [],
    }
    out_path = builder_editor._save_state_version(state)
    assert out_path.exists()
    assert "Курсовая_работа" in out_path.name
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["title"] == "Курсовая работа"


def test_save_state_version_sanitizes_title(tmp_path: Path, monkeypatch) -> None:
    """Спецсимволы в title не ломают имя файла."""
    from gostforge.web import builder_editor

    monkeypatch.setattr(builder_editor, "_state_versions_dir", lambda: tmp_path)
    state = {"title": "Работа/с\\плохими:символами?", "sections": []}
    out_path = builder_editor._save_state_version(state)
    # Спецсимволов в имени нет — только slash и .json.
    assert "/" not in out_path.name
    assert "\\" not in out_path.name
    assert ":" not in out_path.name
    assert "?" not in out_path.name


def test_save_state_version_prunes_old(tmp_path: Path, monkeypatch) -> None:
    """Старые версии подрезаются до _VERSION_KEEP_COUNT (30)."""
    from gostforge.web import builder_editor

    monkeypatch.setattr(builder_editor, "_state_versions_dir", lambda: tmp_path)
    monkeypatch.setattr(builder_editor, "_VERSION_KEEP_COUNT", 3)
    import time

    for i in range(5):
        state = {"title": f"work-{i}", "sections": []}
        builder_editor._save_state_version(state)
        # Уникальный mtime для каждой версии.
        time.sleep(0.01)
    # Должно остаться только 3 (последние).
    files = list(tmp_path.glob("*.json"))
    assert len(files) <= 3


def test_list_state_versions_sorted_newest_first(tmp_path: Path, monkeypatch) -> None:
    from gostforge.web import builder_editor

    monkeypatch.setattr(builder_editor, "_state_versions_dir", lambda: tmp_path)
    import time

    for i in range(3):
        state = {"title": f"v{i}", "sections": []}
        builder_editor._save_state_version(state)
        time.sleep(0.01)
    versions = builder_editor.list_state_versions()
    assert len(versions) == 3
    # Mtime сортирован по убыванию.
    mtimes = [p.stat().st_mtime for p in versions]
    assert mtimes == sorted(mtimes, reverse=True)


# --- CLI state-versions ---


def test_cli_state_versions_list_empty(tmp_path: Path, monkeypatch) -> None:
    """Когда нет версий — CLI выводит «Версий не найдено»."""
    monkeypatch.setenv("HOME", str(tmp_path))
    r = subprocess.run(
        ["gostforge", "state-versions", "list"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "Версий" in r.stdout


def test_cli_state_versions_restore_without_arg_fails(tmp_path: Path, monkeypatch) -> None:
    """`state-versions restore` без указания файла → exit 2."""
    monkeypatch.setenv("HOME", str(tmp_path))
    r = subprocess.run(
        ["gostforge", "state-versions", "restore"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "filename" in r.stderr or "filename" in r.stdout


def test_cli_state_versions_restore_creates_file(tmp_path: Path, monkeypatch) -> None:
    """Восстановление: версия копируется в output (или cwd по умолчанию)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Создадим версию вручную.
    versions_dir = tmp_path / ".gostforge" / "state-versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    version_file = versions_dir / "test_work-20260526-120000.json"
    state = {"title": "test_work", "sections": []}
    version_file.write_text(json.dumps(state, ensure_ascii=False))

    out = tmp_path / "restored.json"
    r = subprocess.run(
        [
            "gostforge",
            "state-versions",
            "restore",
            "test_work-20260526-120000.json",
            "-o",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert out.exists()
    restored = json.loads(out.read_text(encoding="utf-8"))
    assert restored["title"] == "test_work"


def test_cli_state_versions_restore_partial_match(tmp_path: Path, monkeypatch) -> None:
    """Если указан частичный match имени — найдём по подстроке."""
    monkeypatch.setenv("HOME", str(tmp_path))
    versions_dir = tmp_path / ".gostforge" / "state-versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    (versions_dir / "kursovaya-20260526-100000.json").write_text('{"title": "k", "sections": []}')
    out = tmp_path / "out.json"
    r = subprocess.run(
        [
            "gostforge",
            "state-versions",
            "restore",
            "kursovaya",
            "-o",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert out.exists()


# --- Live-preview одного раздела ---


def test_render_single_section_preview_importable() -> None:
    from gostforge.web.builder_editor import (
        _render_single_section_pdf_preview,
    )

    assert callable(_render_single_section_pdf_preview)
