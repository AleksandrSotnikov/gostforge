# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты автосохранения visual-builder state (шаг 8 Фазы 2.5).

Изолируем диск через monkeypatch — autosave-каталог редиректим в
tmp_path, чтобы не трогать реальный ~/.gostforge/autosave/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

import streamlit as st

from gostforge.web import builder_editor as be


_RESET_KEYS = (
    "builder_state",
    "builder_history",
    "builder_history_cursor",
    "builder_autosave_ts",
    "builder_autosave_dismissed",
)


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    for key in _RESET_KEYS:
        if key in st.session_state:
            del st.session_state[key]


@pytest.fixture(autouse=True)
def _isolate_autosave_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Подменить ~/.gostforge на временный каталог теста."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _set_state(payload: dict[str, Any]) -> None:
    st.session_state["builder_state"] = payload


def test_autosave_now_writes_json_file() -> None:
    _set_state({"title": "X", "sections": []})
    be._autosave_now()
    payload = json.loads(be._autosave_path().read_text(encoding="utf-8"))
    assert payload == {"title": "X", "sections": []}


def test_autosave_now_skips_when_interval_not_elapsed() -> None:
    _set_state({"title": "A", "sections": []})
    be._autosave_now()
    first_mtime = be._autosave_path().stat().st_mtime
    # Сразу второй раз — должно проигнорироваться (interval=30s).
    _set_state({"title": "B", "sections": []})
    be._autosave_now()
    second_mtime = be._autosave_path().stat().st_mtime
    assert first_mtime == second_mtime
    # Файл всё ещё содержит первое значение.
    payload = json.loads(be._autosave_path().read_text(encoding="utf-8"))
    assert payload["title"] == "A"


def test_autosave_now_writes_again_after_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_state({"title": "A", "sections": []})
    be._autosave_now()
    # Сдвигаем «последний автосейв» в прошлое на 31 секунду.
    st.session_state["builder_autosave_ts"] = time.time() - 31
    _set_state({"title": "B", "sections": []})
    be._autosave_now()
    payload = json.loads(be._autosave_path().read_text(encoding="utf-8"))
    assert payload["title"] == "B"


def test_try_load_autosave_returns_none_when_missing() -> None:
    assert be._try_load_autosave_state() is None


def test_try_load_autosave_returns_state_when_fresh() -> None:
    payload = {"sections": [{"id": "s1", "heading": "Глава", "blocks": []}]}
    be._autosave_path().write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    loaded = be._try_load_autosave_state()
    assert loaded == payload


def test_try_load_autosave_rejects_stale_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Файл старше 24 часов считается устаревшим."""
    path = be._autosave_path()
    path.write_text('{"sections": []}', encoding="utf-8")
    # Делаем файл «старым»: mtime ровно 25 часов назад.
    old_ts = time.time() - 25 * 3600
    import os

    os.utime(path, (old_ts, old_ts))
    assert be._try_load_autosave_state() is None


def test_try_load_autosave_rejects_invalid_json() -> None:
    be._autosave_path().write_text("not a json{", encoding="utf-8")
    assert be._try_load_autosave_state() is None


def test_try_load_autosave_rejects_payload_without_sections() -> None:
    be._autosave_path().write_text('{"title": "x"}', encoding="utf-8")
    assert be._try_load_autosave_state() is None


def test_autosave_dir_created_idempotently() -> None:
    """Повторные вызовы _autosave_dir не падают, даже если каталог уже есть."""
    p1 = be._autosave_dir()
    p2 = be._autosave_dir()
    assert p1 == p2
    assert p1.is_dir()


def test_autosave_does_not_crash_on_io_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если запись на диск падает — autosave логирует и не ломает поток."""

    def _boom(self: Path, data: bytes) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", _boom)
    _set_state({"title": "X", "sections": []})
    be._autosave_now()  # должен молча отработать, без исключения
