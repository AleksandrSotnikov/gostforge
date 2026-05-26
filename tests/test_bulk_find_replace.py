# ruff: noqa: RUF001, RUF002, RUF003

"""Тесты bulk find-replace в конструкторе."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import _bulk_find_replace


def test_replace_in_paragraph_text() -> None:
    state = {
        "sections": [
            {
                "heading": "X",
                "blocks": [
                    {"kind": "paragraph", "text": "БД используется для БД."}
                ],
            }
        ]
    }
    n = _bulk_find_replace(state, "БД", "база данных")
    assert n == 2
    assert state["sections"][0]["blocks"][0]["text"] == (
        "база данных используется для база данных."
    )


def test_replace_in_runs() -> None:
    state = {
        "sections": [
            {
                "heading": "X",
                "blocks": [
                    {
                        "kind": "paragraph",
                        "runs": [
                            {"kind": "text", "text": "старое слово"},
                            {"kind": "text", "text": " и старое", "bold": True},
                        ],
                    }
                ],
            }
        ]
    }
    n = _bulk_find_replace(state, "старое", "новое")
    assert n == 2
    runs = state["sections"][0]["blocks"][0]["runs"]
    assert runs[0]["text"] == "новое слово"
    assert runs[1]["text"] == " и новое"


def test_replace_in_heading() -> None:
    state = {"sections": [{"heading": "Глава про БД", "blocks": []}]}
    n = _bulk_find_replace(state, "БД", "базы данных")
    assert n == 1
    assert state["sections"][0]["heading"] == "Глава про базы данных"


def test_replace_in_list_items() -> None:
    state = {
        "sections": [
            {
                "heading": "Заголовок",
                "blocks": [
                    {
                        "kind": "list",
                        "ordered": False,
                        "items": ["пункт про X", "ещё X"],
                    }
                ],
            }
        ]
    }
    n = _bulk_find_replace(state, "X", "Y")
    assert n == 2
    items = state["sections"][0]["blocks"][0]["items"]
    assert items == ["пункт про Y", "ещё Y"]


def test_replace_in_table_cells() -> None:
    state = {
        "sections": [
            {
                "heading": "X",
                "blocks": [
                    {
                        "kind": "table",
                        "headers": ["foo", "bar"],
                        "rows": [["foo data", "other"]],
                        "caption": "Таблица foo",
                    }
                ],
            }
        ]
    }
    n = _bulk_find_replace(state, "foo", "FOO")
    assert n >= 3  # header + cell + caption
    block = state["sections"][0]["blocks"][0]
    assert block["caption"] == "Таблица FOO"
    assert block["headers"][0] == "FOO"
    assert block["rows"][0][0] == "FOO data"


def test_replace_in_references() -> None:
    state = {
        "sections": [
            {
                "heading": "Список",
                "is_bibliography": True,
                "references": ["Иванов 2007.", "Иванов 2010."],
            }
        ]
    }
    n = _bulk_find_replace(state, "Иванов", "Петров")
    assert n == 2
    assert state["sections"][0]["references"] == ["Петров 2007.", "Петров 2010."]


def test_replace_in_subsections() -> None:
    state = {
        "sections": [
            {
                "heading": "Глава 1",
                "blocks": [],
                "subsections": [
                    {
                        "heading": "Подраздел про foo",
                        "blocks": [
                            {"kind": "paragraph", "text": "foo bar"}
                        ],
                    }
                ],
            }
        ]
    }
    n = _bulk_find_replace(state, "foo", "baz")
    assert n == 2
    sub = state["sections"][0]["subsections"][0]
    assert sub["heading"] == "Подраздел про baz"
    assert sub["blocks"][0]["text"] == "baz bar"


def test_replace_empty_find_no_op() -> None:
    state = {"sections": [{"heading": "X", "blocks": []}]}
    n = _bulk_find_replace(state, "", "Y")
    assert n == 0


def test_replace_not_found() -> None:
    state = {"sections": [{"heading": "X", "blocks": []}]}
    n = _bulk_find_replace(state, "несуществует", "Y")
    assert n == 0
