"""Тесты вкладки документации в Streamlit-UI.

Стримлит-виджеты не дёргаем — проверяем чистые функции
(_list_md_files, _rewrite_relative_links) и факт, что
render_docs_viewer импортируется без ошибок.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from gostforge.web.docs_viewer import (
    _docs_dir,
    _list_md_files,
    _rewrite_relative_links,
    render_docs_viewer,
)


def test_render_docs_viewer_importable() -> None:
    """Функция импортируется и вызываема (smoke)."""
    assert callable(render_docs_viewer)


def test_docs_dir_resolves_to_existing_directory() -> None:
    """В репозитории docs/ существует — функция должна его найти."""
    p = _docs_dir()
    assert p.is_dir()
    assert (p / "architecture.md").is_file()


def test_list_md_files_orders_known_files_first(tmp_path: Path) -> None:
    """Файлы из _MENU_ORDER идут первыми, остальные — по алфавиту."""
    (tmp_path / "architecture.md").write_text("# A")
    (tmp_path / "zz-extra.md").write_text("# Z")
    (tmp_path / "api.md").write_text("# API")

    entries = _list_md_files(tmp_path)
    slugs = [s for s, _ in entries]
    # architecture и api — в порядке _MENU_ORDER (architecture первым).
    assert slugs.index("architecture") < slugs.index("api")
    # Нестандартный файл — в конце.
    assert slugs.index("zz-extra") > slugs.index("api")


def test_list_md_files_returns_human_titles(tmp_path: Path) -> None:
    (tmp_path / "architecture.md").write_text("# A")
    (tmp_path / "custom-extra.md").write_text("# Custom")
    entries = _list_md_files(tmp_path)
    titles = dict(entries)
    # У известного файла — кастомное имя из _MENU_ORDER.
    assert titles["architecture"] == "Архитектура"
    # У неизвестного — slug, форматированный из имени файла.
    assert "Custom" in titles["custom-extra"]


def test_list_md_files_empty_dir(tmp_path: Path) -> None:
    assert _list_md_files(tmp_path) == []


def test_list_md_files_missing_dir(tmp_path: Path) -> None:
    """Если каталога нет — пустой список (вместо exception)."""
    assert _list_md_files(tmp_path / "nope") == []


# --- _rewrite_relative_links ----------------------------------------------


def test_rewrite_relative_md_link_to_italic() -> None:
    """Ссылка на другой .md файл становится italics-подсказкой."""
    raw = "См. [Архитектуру](architecture.md) для деталей."
    out = _rewrite_relative_links(raw)
    assert "(architecture.md)" not in out
    assert "_Архитектуру_" in out


def test_rewrite_keeps_http_links() -> None:
    raw = "Подробности на [сайте](https://example.com/foo)."
    out = _rewrite_relative_links(raw)
    assert "[сайте](https://example.com/foo)" in out


def test_rewrite_keeps_anchor_only_links() -> None:
    """Якорные ссылки внутри страницы (#section) — оставляем как есть."""
    raw = "См. [ниже](#section-2)."
    out = _rewrite_relative_links(raw)
    assert "[ниже](#section-2)" in out


def test_rewrite_handles_md_with_anchor() -> None:
    """file.md#anchor — это тоже относительная ссылка, italics."""
    raw = "См. [секцию 4.1](builder.md#41-пословное-редактирование)."
    out = _rewrite_relative_links(raw)
    assert "(builder.md" not in out
    assert "_секцию 4.1_" in out


def test_rewrite_keeps_mailto_links() -> None:
    raw = "Пишите на [почту](mailto:dev@example.com)."
    out = _rewrite_relative_links(raw)
    assert "mailto:dev@example.com" in out


def test_rewrite_handles_text_without_links() -> None:
    raw = "Простой текст без ссылок."
    assert _rewrite_relative_links(raw) == raw


# --- Реальные docs/ файлы в репозитории ------------------------------------


def test_real_docs_dir_has_expected_files() -> None:
    """В docs/ репозитория есть основные файлы из _MENU_ORDER."""
    p = _docs_dir()
    expected = {
        "architecture",
        "builder",
        "checks-catalog",
        "profiles",
        "api",
        "database",
        "roadmap",
    }
    actual = {f.stem for f in p.glob("*.md")}
    assert expected <= actual


def test_real_docs_render_without_error() -> None:
    """Каждый md-файл в docs/ читается и rewrite_relative_links не падает."""
    p = _docs_dir()
    for md in p.glob("*.md"):
        text = md.read_text(encoding="utf-8")
        rewritten = _rewrite_relative_links(text)
        # Преобразование не должно ломать markdown-структуру.
        assert isinstance(rewritten, str)
        assert len(rewritten) > 0
