# ruff: noqa: RUF001, RUF002, RUF003

"""Streamlit-страница для просмотра документации проекта.

Третий режим веб-интерфейса (помимо «Нормоконтроль» и «Конструктор»):
встроенный просмотр markdown-документации из каталога ``docs/``.

Зачем это в WebApp:

* Пользователю (студенту/кафедре), который зашёл через браузер,
  не нужно открывать GitHub или клонировать репозиторий, чтобы
  прочитать руководство.
* Документация и UI всегда одной версии — поставка идёт одним
  Docker-образом / pip-пакетом.
* Mobile-friendly: открывается с любого устройства через тот же
  Streamlit-сервис.

Содержимое — статические файлы из каталога ``docs/`` (находится в
корне репозитория). Поддерживается список разделов в sidebar,
рендеринг через ``st.markdown``, относительные ссылки между файлами
автоматически переводятся в навигацию внутри страницы.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        'Установите gostforge[ui] для веб-интерфейса: pip install -e ".[ui]"'
    ) from exc


# Заголовки для основных файлов docs/, в нужном порядке для меню.
# Каждый элемент: (имя файла без .md, человекочитаемое имя).
# Файлы не из списка добавляются в конец автоматически.
_MENU_ORDER: list[tuple[str, str]] = [
    ("architecture", "Архитектура"),
    ("builder", "Конструктор работ"),
    ("checks-catalog", "Каталог проверок"),
    ("profiles", "Профили и маркетплейс"),
    ("database", "Локальная БД"),
    ("api", "REST API"),
    ("plugins", "Плагины проверок"),
    ("page-sections", "Колонтитулы и секции"),
    ("roadmap", "Roadmap"),
    ("phase-2.5-spec", "ТЗ Фазы 2.5"),
    ("phase-3-api-spec", "ТЗ Фазы 3 (API)"),
    ("claude-code-workflow", "Работа с Claude Code"),
]


def _docs_dir() -> Path:
    """Каталог с документацией.

    Ищем относительно установленного пакета: ``gostforge`` лежит в
    ``src/gostforge/``, ``docs/`` — на 3 уровня выше (для editable-install)
    или рядом с пакетом в кастомных сборках. Если не нашли — возвращаем
    None-эквивалент (несуществующий путь), вызывающая сторона покажет
    сообщение.
    """
    here = Path(__file__).resolve()
    # src/gostforge/web/docs_viewer.py → parents:
    # [0]=web, [1]=gostforge, [2]=src, [3]=repo-root
    candidates = [
        here.parents[3] / "docs",
        here.parents[2] / "docs",
        here.parents[1] / "docs",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]  # несуществующий — обработаем в UI


def _list_md_files(docs_dir: Path) -> list[tuple[str, str]]:
    """Список (slug, title) для меню.

    Сначала идут файлы из ``_MENU_ORDER`` (в заданном порядке),
    потом — все остальные ``*.md`` по алфавиту.
    """
    if not docs_dir.is_dir():
        return []
    available = {f.stem for f in docs_dir.glob("*.md")}
    result: list[tuple[str, str]] = []
    used: set[str] = set()
    for slug, title in _MENU_ORDER:
        if slug in available:
            result.append((slug, title))
            used.add(slug)
    extra = sorted(available - used)
    for slug in extra:
        result.append((slug, slug.replace("-", " ").capitalize()))
    return result


def _rewrite_relative_links(markdown_text: str) -> str:
    """Переписать относительные ссылки между md-файлами на якоря.

    Streamlit не умеет переходить между разными ``st.markdown``-страницами
    по ``[text](other.md)`` — мы конвертируем такие ссылки в подсказку
    «выберите раздел в меню слева».
    """
    # Ссылки вида [text](file.md) или [text](file.md#anchor) — заменяем на
    # markdown-курсив с подсказкой.
    def _replace(match: re.Match[str]) -> str:
        text = match.group(1)
        target = match.group(2)
        # Внешние ссылки (http(s)://, mailto:) не трогаем.
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return match.group(0)
        # Относительная ссылка на .md → подсказка в меню.
        if target.endswith(".md") or ".md#" in target:
            return f"_{text}_"
        return match.group(0)

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _replace, markdown_text)


def render_docs_viewer() -> None:
    """Главная функция режима «Документация»."""
    st.title("Документация gostforge")
    st.caption(
        "Полное руководство — здесь. Меню разделов слева; для разработчиков "
        "те же файлы лежат в каталоге `docs/` репозитория."
    )

    docs_dir = _docs_dir()
    if not docs_dir.is_dir():
        st.error(
            f"Каталог документации не найден ({docs_dir}). "
            "Похоже, gostforge установлен без файлов docs/. "
            "Полная документация доступна в репозитории проекта."
        )
        return

    entries = _list_md_files(docs_dir)
    if not entries:
        st.warning("В каталоге `docs/` нет ни одного .md-файла.")
        return

    # Меню в sidebar: показываем человеческие имена, slug используем как ключ.
    titles = [title for _, title in entries]
    slugs = [slug for slug, _ in entries]
    default = 0
    selected_title = st.sidebar.radio(
        "Раздел",
        options=titles,
        index=default,
        key="docs_viewer_section",
    )
    selected_slug = slugs[titles.index(selected_title)]

    md_path = docs_dir / f"{selected_slug}.md"
    if not md_path.is_file():  # pragma: no cover - меню синхронно с файлами
        st.error(f"Файл {md_path.name} не найден.")
        return

    raw = md_path.read_text(encoding="utf-8")
    rendered = _rewrite_relative_links(raw)

    # Кнопка «Скачать .md» — на случай, если пользователь хочет утащить
    # файл с собой (например, для печати).
    st.sidebar.download_button(
        "Скачать .md",
        data=raw.encode("utf-8"),
        file_name=md_path.name,
        mime="text/markdown",
        key="docs_viewer_download",
    )

    st.markdown(rendered, unsafe_allow_html=False)


__all__ = ["render_docs_viewer"]
