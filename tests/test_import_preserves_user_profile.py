# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты что _handle_docx_import сохраняет profile_id, выбранный
пользователем в sidebar — не перезаписывает дефолтом из импортируемого
документа.

ПРОБЛЕМА. Пользователь выбирает gost-r-2.105-2019, загружает docx.
В метаданных docx profile_id пустой или дефолтный gost-7.32-2017,
после parse_docx → document_to_state state получает дефолт, и в
sidebar selectbox переключается на gost-7.32-2017.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import streamlit as st

from gostforge.builder import work
from gostforge.exporter import export_docx
from gostforge.profile import load_profile
from gostforge.web.builder_editor import _handle_docx_import


@pytest.fixture(autouse=True)
def _reset_session_state() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _make_docx(tmp_path: Path, profile_id: str = "gost-7.32-2017") -> bytes:
    """Сгенерировать минимальный .docx через builder."""
    b = (
        work("X", year=2026)
        .section("Введение")
        .paragraph("Текст.")
        .section("Список использованных источников")
        .reference("Кнут — М., 2007.")
    )
    out = tmp_path / "src.docx"
    export_docx(b.build(), load_profile(profile_id), out)
    return out.read_bytes()


def test_import_preserves_user_selected_profile_eskd(tmp_path: Path) -> None:
    """Студент выбрал ЕСКД, импортируется docx с дефолтным профилем →
    после импорта в state остаётся ЕСКД."""
    st.session_state["builder_state"] = {
        "title": "Текущая работа",
        "year": 2026,
        "profile_id": "gost-r-2.105-2019",  # выбран пользователем
        "sections": [],
        "active_section_index": 0,
    }
    docx_bytes = _make_docx(tmp_path)  # генерируется с gost-7.32-2017

    # _handle_docx_import зовёт st.rerun() в конце — пытаемся
    # просто запустить и проверить state после, либо catch
    # NoSessionContext.
    try:
        _handle_docx_import(docx_bytes, "loaded.docx")
    except Exception:
        # st.rerun() вне Streamlit-сессии бросает — это OK,
        # state уже обновлён.
        pass

    assert (
        st.session_state["builder_state"]["profile_id"]
        == "gost-r-2.105-2019"
    ), (
        "profile_id переключился с ЕСКД на дефолт после импорта — "
        "пользовательский выбор был утрачен."
    )


def test_import_uses_doc_profile_when_no_user_selection(
    tmp_path: Path,
) -> None:
    """Если в session_state нет profile_id (свежая сессия), берём из
    импортированного документа."""
    # Не ставим builder_state вообще.
    docx_bytes = _make_docx(tmp_path, profile_id="gost-7.32-2017")
    try:
        _handle_docx_import(docx_bytes, "loaded.docx")
    except Exception:
        pass

    # Должен взять из документа (gost-7.32-2017).
    state = st.session_state.get("builder_state", {})
    assert state.get("profile_id") == "gost-7.32-2017"


def test_import_preserves_eskd_through_multiple_docx_loads(
    tmp_path: Path,
) -> None:
    """Многократная загрузка разных .docx не должна сбивать выбранный
    профиль."""
    st.session_state["builder_state"] = {
        "title": "X",
        "year": 2026,
        "profile_id": "gost-r-2.105-2019",
        "sections": [],
        "active_section_index": 0,
    }
    # Первая загрузка.
    docx1 = _make_docx(tmp_path)
    try:
        _handle_docx_import(docx1, "a.docx")
    except Exception:
        pass
    # Вторая загрузка.
    docx2 = _make_docx(tmp_path)
    try:
        _handle_docx_import(docx2, "b.docx")
    except Exception:
        pass

    assert (
        st.session_state["builder_state"]["profile_id"]
        == "gost-r-2.105-2019"
    )
