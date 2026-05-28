"""Тесты для багфиксов конструктора: подписи таблиц/рисунков и блок-id.

Покрывает два бага, найденные пользователем:

1. **Дублирование префиксов «Таблица N — Таблица N — ...»** при
   повторной вставке документа. Префикс должен сниматься для разных
   форматов разделителя (em-dash, en-dash, дефис, точка, двоеточие,
   многоуровневая нумерация, NBSP) и итеративно, если он уже задвоён.
2. **Удаление/перемещение блоков «прилипало» к соседу** — Streamlit
   кэшировал значения виджетов по позиционному ключу, после ``pop``
   индексы сдвигались и блок на новой позиции получал чужой state.
   Фикс: стабильный per-block id, свежий id у клонов.
"""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")

from gostforge.web.builder_editor import (
    _duplicate_block,
    _new_block_id,
    _purge_block_ids_recursively,
    _purge_section_ids_recursively,
    _strip_caption_prefix,
)

# --- Подписи таблиц и рисунков ----------------------------------------------


@pytest.mark.parametrize(
    "caption",
    [
        "Таблица 1 — Параметры",
        "Таблица 1 - Параметры",
        "Таблица 1 – Параметры",
        "Таблица 1. Параметры",
        "Таблица 1: Параметры",
        "Таблица 1.2 — Параметры",
        "Таблица 1 — Параметры",
    ],
)
def test_strip_caption_prefix_recognises_various_separators(caption: str) -> None:
    """Все распространённые формы префикса «Таблица N <sep>» режутся до «Параметры»."""
    assert _strip_caption_prefix(caption, kind="table") == "Параметры"


def test_strip_caption_prefix_iterative_unwraps_doubled() -> None:
    """Уже задвоённый префикс снимается до полностью голой подписи."""
    text = "Таблица 1 — Таблица 1 — Параметры"
    assert _strip_caption_prefix(text, kind="table") == "Параметры"


def test_strip_caption_prefix_iterative_unwraps_triple() -> None:
    """Префикс трижды — снимаем всё."""
    text = "Таблица 1 — Таблица 2 — Таблица 3 — Финал"
    assert _strip_caption_prefix(text, kind="table") == "Финал"


def test_strip_caption_prefix_no_prefix_unchanged() -> None:
    """Если префикса нет — текст не меняется."""
    assert _strip_caption_prefix("Параметры эксперимента", kind="table") == "Параметры эксперимента"


def test_strip_caption_prefix_figure_kind() -> None:
    """Аналогично для рисунков (`Рисунок N — ...`)."""
    assert _strip_caption_prefix("Рисунок 1 — Схема", kind="figure") == "Схема"
    assert _strip_caption_prefix("Рисунок 1 — Рисунок 1 — Схема", kind="figure") == "Схема"
    # «Таблица» как kind="figure" не трогается (другое слово).
    assert _strip_caption_prefix("Таблица 1 — Foo", kind="figure") == "Таблица 1 — Foo"


# --- Стабильные id блоков ---------------------------------------------------


def test_new_block_id_is_unique_and_short() -> None:
    """`_new_block_id` каждый раз генерирует разный 8-символьный hex."""
    ids = {_new_block_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) == 8 and all(c in "0123456789abcdef" for c in i) for i in ids)


def test_duplicate_block_strips_id_so_clone_gets_fresh_one() -> None:
    """После `_duplicate_block` клон не имеет `id` — он будет назначен при рендере."""
    blocks: list[dict[str, object]] = [
        {"kind": "paragraph", "runs": [], "id": "abcd1234"},
        {"kind": "paragraph", "runs": []},
    ]
    _duplicate_block(blocks, 0)
    # Оригинал остался с прежним id.
    assert blocks[0].get("id") == "abcd1234"
    # Клон вставлен сразу после, у него id отсутствует — будет назначен на ренде.
    assert blocks[1].get("kind") == "paragraph"
    assert "id" not in blocks[1]


def test_purge_block_ids_recursively_clears_blocks_and_subsections() -> None:
    """`_purge_block_ids_recursively` очищает id во всех вложенных блоках."""
    section = {
        "id": "s1",
        "blocks": [
            {"kind": "paragraph", "id": "b1"},
            {"kind": "table", "id": "b2"},
        ],
        "subsections": [
            {
                "id": "s1a",
                "blocks": [{"kind": "paragraph", "id": "b3"}],
                "subsections": [
                    {
                        "id": "s1a1",
                        "blocks": [{"kind": "figure", "id": "b4"}],
                        "subsections": [],
                    }
                ],
            }
        ],
    }
    _purge_block_ids_recursively(section)
    # Section.id остаётся (это другая сущность); id-блоков убраны.
    assert section["id"] == "s1"
    assert all("id" not in b for b in section["blocks"])
    sub = section["subsections"][0]
    assert all("id" not in b for b in sub["blocks"])
    subsub = sub["subsections"][0]
    assert all("id" not in b for b in subsub["blocks"])


def test_purge_block_ids_handles_missing_keys() -> None:
    """Раздел без блоков/подразделов не падает."""
    section: dict[str, object] = {"id": "s", "heading": "x"}
    _purge_block_ids_recursively(section)  # должно отработать без ошибок
    assert section == {"id": "s", "heading": "x"}


def test_purge_section_ids_recursively_clears_nested_subsections() -> None:
    """`_purge_section_ids_recursively` очищает id у самой секции и всех подразделов."""
    section = {
        "id": "sec-1",
        "heading": "Глава 1",
        "subsections": [
            {
                "id": "sub-1-1",
                "heading": "1.1",
                "subsections": [
                    {"id": "subsub-1-1-1", "heading": "1.1.1", "subsections": []}
                ],
            }
        ],
    }
    _purge_section_ids_recursively(section)
    assert "id" not in section
    sub = section["subsections"][0]
    assert "id" not in sub
    subsub = sub["subsections"][0]
    assert "id" not in subsub
    # heading и структура сохраняются.
    assert section["heading"] == "Глава 1"
