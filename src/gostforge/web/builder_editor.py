# ruff: noqa: RUF001, RUF002, RUF003

"""Интерактивный визуальный конструктор работ для Streamlit.

Реализует второй режим веб-интерфейса — полноценный редактор, где
студент:

* создаёт работу с нуля или загружает шаблон;
* интерактивно добавляет/удаляет/перемещает разделы и подразделы;
* в каждом разделе редактирует блоки: параграф, таблица, рисунок,
  список, формула, ссылка на источник литературы;
* видит live-предпросмотр структуры работы;
* сохраняет промежуточное состояние в JSON и загружает обратно;
* по кнопке «Сгенерировать .docx» получает готовый файл и сразу
  видит сводку нарушений выбранного профиля.

Единственный источник истины — ``st.session_state.builder_state``.
Любое действие пользователя мутирует state, после чего Streamlit
перерисовывает страницу.

Логика сборки документа из state (``_build_document_from_state``) и
обратное преобразование ``Document → state`` (``_document_to_state``)
вынесены в отдельные функции, чтобы их можно было покрыть unit-тестами
без поднятия Streamlit-сессии.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - streamlit обязателен в режиме UI
    raise ImportError(
        'Установите gostforge[ui] для веб-интерфейса: pip install -e ".[ui]"'
    ) from exc

from gostforge import __version__
from gostforge.builder import work
from gostforge.builder.templates import (
    bachelor_thesis_template,
    coursework_template,
    research_report_template,
)
from gostforge.exporter import export_docx
from gostforge.model import (
    Figure,
    Formula,
    ListBlock,
    LogicalSection,
    Paragraph,
    Table,
    TextRun,
)
from gostforge.profile import list_profiles, load_profile
from gostforge.validator import validate

if TYPE_CHECKING:
    from gostforge.builder.section_builder import SectionBuilder
    from gostforge.model import Document


# --- Константы ---------------------------------------------------------------


# Метки шаблонов для UI (id шаблона → человекочитаемое имя).
_TEMPLATE_LABELS: dict[str, str] = {
    "coursework": "Курсовая работа",
    "bachelor_thesis": "Бакалаврская ВКР",
    "research_report": "Отчёт о НИР",
}

# Алиасы заголовков раздела «Список использованных источников» — нужны для
# распознавания при загрузке шаблона/документа в state.
_BIBLIOGRAPHY_HEADINGS: frozenset[str] = frozenset(
    {
        "список использованных источников",
        "список литературы",
        "библиографический список",
        "список источников",
    }
)

# Виды работ для селектора.
_WORK_TYPE_LABELS: dict[str, str] = {
    "coursework": "Курсовая",
    "bachelor_thesis": "Бакалаврская ВКР",
    "master_thesis": "Магистерская ВКР",
    "research_report": "Отчёт о НИР",
    "other": "Другое",
}

# Допустимые виды блоков. Объявлен как Literal-аналог для удобства проверки.
BlockKind = Literal["paragraph", "table", "figure", "list", "formula"]


# --- State -------------------------------------------------------------------


def _default_state() -> dict[str, Any]:
    """Создать дефолтное (пустое) состояние конструктора.

    В нём — один обязательный раздел «Введение» с пустым параграфом и
    раздел «Список использованных источников» (маркируется как
    bibliography). Это даёт студенту минимально валидную отправную
    точку: список разделов не пуст, главная область сразу что-то
    показывает.
    """
    return {
        "title": "",
        "author": "",
        "supervisor": "",
        "organization": "",
        "year": 2026,
        "work_type": "coursework",
        "profile_id": "gost-7.32-2017",
        "active_section_index": 0,
        "sections": [
            {
                "id": "intro",
                "heading": "Введение",
                "blocks": [{"kind": "paragraph", "text": ""}],
                "subsections": [],
            },
            {
                "id": "bibliography",
                "heading": "Список использованных источников",
                "blocks": [],
                "subsections": [],
                "is_bibliography": True,
                "references": [],
            },
        ],
    }


def _ensure_state() -> None:
    """Положить в session_state дефолтный state, если его ещё нет."""
    if "builder_state" not in st.session_state:
        st.session_state["builder_state"] = _default_state()


def _get_state() -> dict[str, Any]:
    """Вернуть текущий builder_state. Перед использованием — _ensure_state()."""
    state: dict[str, Any] = st.session_state["builder_state"]
    return state


# --- Шаблоны → state ---------------------------------------------------------


def _load_template_to_state(
    template_id: str,
    *,
    title: str = "",
    author: str = "",
    supervisor: str = "",
    organization: str = "",
    year: int = 2026,
) -> dict[str, Any]:
    """Превратить шаблон builder.templates в state-дикт.

    Используется кнопкой «Загрузить шаблон» в sidebar. Берём готовый
    `WorkBuilder` из соответствующей фабрики, делаем `.build()` и
    разворачиваем результат через `_document_to_state`. Это
    гарантирует, что state получится тем же, как если бы студент
    набрал разделы вручную.
    """
    if template_id == "coursework":
        builder = coursework_template(
            title=title or "Курсовая работа",
            author=author,
            supervisor=supervisor,
            organization=organization,
            year=year,
        )
    elif template_id == "bachelor_thesis":
        builder = bachelor_thesis_template(
            title=title or "Бакалаврская работа",
            author=author,
            supervisor=supervisor,
            organization=organization,
            year=year,
        )
    elif template_id == "research_report":
        builder = research_report_template(
            title=title or "Отчёт о НИР",
            year=year,
            organization=organization,
        )
    else:  # pragma: no cover - в UI селект ограничен ключами _TEMPLATE_LABELS
        raise ValueError(f"Неизвестный шаблон: {template_id}")

    document = builder.build()
    state = _document_to_state(document)
    # Перезаписываем метаданные пользовательскими значениями (build()
    # возвращает их через DocumentMetadata, но мы хотим, чтобы field-ы
    # state были не пустыми, даже если шаблон сам их не передаёт).
    state["title"] = document.metadata.title or title
    state["author"] = document.metadata.author or author
    state["supervisor"] = document.metadata.supervisor or supervisor
    state["organization"] = document.metadata.organization or organization
    state["year"] = document.metadata.year or year
    state["work_type"] = document.metadata.work_type
    state["profile_id"] = document.profile_id
    state["active_section_index"] = 0
    return state


# --- Document → state -------------------------------------------------------


def _document_to_state(document: Document) -> dict[str, Any]:
    """Сериализовать Document в state-дикт для редактора.

    Берём только то, что редактор реально умеет редактировать. Всё, что
    в модель кладёт `WorkBuilder` дополнительно (PageSection, footer,
    pgNumType) — отбрасывается, потому что эти параметры пересоздаются
    при следующем build из state.
    """
    sections: list[dict[str, Any]] = []
    for page_section in document.page_sections:
        for child in page_section.content:
            if isinstance(child, LogicalSection):
                sections.append(_logical_section_to_state(child))

    return {
        "title": document.metadata.title,
        "author": document.metadata.author,
        "supervisor": document.metadata.supervisor,
        "organization": document.metadata.organization,
        "year": document.metadata.year or 2026,
        "work_type": document.metadata.work_type,
        "profile_id": document.profile_id,
        "active_section_index": 0,
        "sections": sections,
    }


def _logical_section_to_state(section: LogicalSection) -> dict[str, Any]:
    """Сериализовать один LogicalSection в state-дикт."""
    heading_text = _inline_to_text(section.heading)
    is_bib = heading_text.strip().lower() in _BIBLIOGRAPHY_HEADINGS

    blocks: list[dict[str, Any]] = []
    subsections: list[dict[str, Any]] = []
    references: list[str] = []

    for child in section.children:
        if isinstance(child, LogicalSection):
            subsections.append(_logical_section_to_state(child))
        elif isinstance(child, Paragraph):
            text = _inline_to_text(child.content)
            if is_bib:
                # В разделе «Список ...» параграфы трактуем как ссылки.
                if text.strip():
                    references.append(text)
            else:
                blocks.append({"kind": "paragraph", "text": text})
        elif isinstance(child, Table):
            blocks.append(
                {
                    "kind": "table",
                    "headers": [_inline_to_text(h) for h in child.headers],
                    "rows": [[_inline_to_text(cell) for cell in row] for row in child.rows],
                    "caption": _strip_caption_prefix(_inline_to_text(child.caption), kind="table"),
                }
            )
        elif isinstance(child, Figure):
            blocks.append(
                {
                    "kind": "figure",
                    "image_path": child.image_path,
                    "caption": _strip_caption_prefix(_inline_to_text(child.caption), kind="figure"),
                }
            )
        elif isinstance(child, Formula):
            blocks.append(
                {
                    "kind": "formula",
                    "latex": child.latex,
                    "numbered": child.number is not None,
                }
            )
        elif isinstance(child, ListBlock):
            blocks.append(
                {
                    "kind": "list",
                    "items": [_inline_to_text(item) for item in child.items],
                    "ordered": child.ordered,
                }
            )

    result: dict[str, Any] = {
        "id": section.id,
        "heading": heading_text,
        "blocks": blocks,
        "subsections": subsections,
    }
    if is_bib:
        result["is_bibliography"] = True
        result["references"] = references
    return result


def _inline_to_text(inline: list[Any]) -> str:
    """Склеить список InlineElement (TextRun/CrossRef) в строку."""
    parts: list[str] = []
    for el in inline:
        if isinstance(el, TextRun):
            parts.append(el.text)
    return "".join(parts)


def _strip_caption_prefix(caption: str, *, kind: Literal["table", "figure"]) -> str:
    """Убрать «Таблица N — » / «Рисунок N — » префикс, если он есть.

    Builder сам добавляет такой префикс при экспорте; в state мы храним
    «голую» подпись, чтобы при следующей сборке не получить «Таблица 1
    — Таблица 1 — ...».
    """
    text = caption.strip()
    prefix_word = "Таблица" if kind == "table" else "Рисунок"
    if not text.startswith(prefix_word):
        return text
    rest = text[len(prefix_word) :].lstrip()
    # Ожидаем «N — ...» или «N - ...»; ищем em-dash или дефис после числа.
    for sep in (" — ", " - "):
        idx = rest.find(sep)
        if idx != -1 and rest[:idx].strip().isdigit():
            return rest[idx + len(sep) :].strip()
    return text


# --- state → Document → bytes -----------------------------------------------


def _build_document_from_state(state: dict[str, Any]) -> bytes:
    """Собрать .docx из state и вернуть его байты.

    Возможные ошибки сборки (валидация в `WorkBuilder.save`) пробрасываются
    наружу — UI ловит их и показывает через ``st.error``.
    """
    title = state.get("title") or "Без названия"
    work_type = cast(
        "Literal['coursework', 'bachelor_thesis', 'master_thesis', 'research_report', 'other']",
        state.get("work_type", "coursework"),
    )
    builder = work(
        title=title,
        author=state.get("author", ""),
        year=state.get("year") or None,
        work_type=work_type,
        profile_id=state.get("profile_id", "gost-7.32-2017"),
        supervisor=state.get("supervisor", ""),
        organization=state.get("organization", ""),
    )

    sections = state.get("sections") or []
    if not sections:
        # WorkBuilder без разделов всё равно соберётся, но получится
        # документ с одной пустой main-секцией и без логических разделов.
        # Добавим минимальный раздел «Введение», чтобы build() не
        # выдавал ошибку S.01 на пустой работе.
        builder.section("Введение").paragraph("")
    else:
        for sec in sections:
            sec_builder = builder.section(sec.get("heading", "Раздел"))
            _apply_blocks(sec_builder, sec.get("blocks") or [])
            for sub in sec.get("subsections") or []:
                sub_builder = sec_builder.subsection(sub.get("heading", "Подраздел"))
                _apply_blocks(sub_builder, sub.get("blocks") or [])
            if sec.get("is_bibliography"):
                for ref in sec.get("references") or []:
                    if isinstance(ref, str) and ref.strip():
                        sec_builder.reference(ref)

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        out_path = Path(tmp.name)
    # Используем экспорт напрямую, чтобы не зависеть от валидации в .save():
    # документ может быть «черновиком» с пустыми блоками — это нормально.
    document = builder.build()
    profile_id = state.get("profile_id") or document.profile_id
    profile = load_profile(profile_id)
    export_docx(document, profile, out_path)
    return out_path.read_bytes()


def _apply_blocks(section_builder: SectionBuilder, blocks: list[dict[str, Any]]) -> None:
    """Применить список блоков из state к SectionBuilder.

    Неизвестные типы блоков и пустые поля просто пропускаются — это
    форма «толерантного» поведения для частично заполненного state.
    """
    for block in blocks:
        kind = block.get("kind")
        if kind == "paragraph":
            section_builder.paragraph(block.get("text", ""))
        elif kind == "table":
            headers = list(block.get("headers") or [])
            rows = [list(r) for r in (block.get("rows") or [])]
            caption = block.get("caption", "")
            if not headers and not rows:
                continue
            # Все ячейки должны быть str — на всякий случай приводим.
            headers = [str(h) for h in headers]
            rows = [[str(c) for c in r] for r in rows]
            section_builder.table(headers=headers, rows=rows, caption=str(caption))
        elif kind == "figure":
            image_path = block.get("image_path") or ""
            caption = block.get("caption", "")
            section_builder.image(image_path=image_path, caption=str(caption))
        elif kind == "list":
            items = [str(i) for i in (block.get("items") or [])]
            if not items:
                continue
            section_builder.list(items, ordered=bool(block.get("ordered", False)))
        elif kind == "formula":
            latex = block.get("latex") or ""
            if not latex:
                continue
            section_builder.formula(str(latex), numbered=bool(block.get("numbered", True)))


# --- Валидация для preview ---------------------------------------------------


def _validate_state_bytes(data: bytes, profile_id: str) -> dict[str, int]:
    """Распарсить байты .docx и вернуть счётчик violation по severity.

    Используется для отображения live-предпросмотра после генерации.
    Если что-то пошло не так — возвращаем пустой счётчик.
    """
    from gostforge.parser import parse_docx

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        document = parse_docx(tmp_path)
        profile = load_profile(profile_id)
        violations = validate(document, profile)
    except Exception:  # pragma: no cover - смягчаем ошибки парсинга
        return {}
    counts: Counter[str] = Counter(v.severity for v in violations)
    return dict(counts)


# --- UI: sidebar -------------------------------------------------------------


def _render_sidebar_metadata() -> None:
    """Sidebar с метаданными работы, выбором профиля и save/load JSON."""
    state = _get_state()
    st.sidebar.title("Параметры работы")
    st.sidebar.caption(f"gostforge v{__version__}")

    state["title"] = st.sidebar.text_input(
        "Название работы",
        value=state.get("title", ""),
        help="Обязательное поле. Используется на титульном листе.",
    )
    state["author"] = st.sidebar.text_input(
        "Автор",
        value=state.get("author", ""),
        help="ФИО автора. Для отчёта о НИР игнорируется.",
    )
    state["supervisor"] = st.sidebar.text_input(
        "Научный руководитель",
        value=state.get("supervisor", ""),
    )
    state["organization"] = st.sidebar.text_input(
        "Организация",
        value=state.get("organization", ""),
    )
    state["year"] = int(
        st.sidebar.number_input(
            "Год",
            min_value=1900,
            max_value=2100,
            value=int(state.get("year", 2026)),
            step=1,
        )
    )

    work_types = list(_WORK_TYPE_LABELS.keys())
    current_wt = state.get("work_type", "coursework")
    state["work_type"] = st.sidebar.selectbox(
        "Вид работы",
        options=work_types,
        index=work_types.index(current_wt) if current_wt in work_types else 0,
        format_func=lambda key: _WORK_TYPE_LABELS[key],
    )

    profiles = list_profiles()
    current_profile = state.get("profile_id", "gost-7.32-2017")
    state["profile_id"] = st.sidebar.selectbox(
        "Профиль",
        options=profiles,
        index=(profiles.index(current_profile) if current_profile in profiles else 0),
        help="Профиль определяет, какие проверки нормоконтроля будут запущены.",
    )

    st.sidebar.divider()
    st.sidebar.subheader("Шаблоны")
    template_id = st.sidebar.selectbox(
        "Заготовка",
        options=list(_TEMPLATE_LABELS.keys()),
        format_func=lambda key: _TEMPLATE_LABELS[key],
        key="builder_template_pick",
    )
    if st.sidebar.button("Загрузить шаблон", key="builder_load_template"):
        st.session_state["builder_state"] = _load_template_to_state(
            template_id,
            title=state.get("title", ""),
            author=state.get("author", ""),
            supervisor=state.get("supervisor", ""),
            organization=state.get("organization", ""),
            year=int(state.get("year", 2026)),
        )
        st.rerun()

    if st.sidebar.button("Сбросить", key="builder_reset"):
        st.session_state["builder_state"] = _default_state()
        st.rerun()

    _render_state_persistence_sidebar(state)


# --- UI: section tree --------------------------------------------------------


def _render_section_tree() -> None:
    """Список разделов с кнопками ↑/↓/✕ и выбором активного раздела."""
    state = _get_state()
    sections = state["sections"]

    st.subheader("Разделы работы")
    if not sections:
        st.info("Нет ни одного раздела. Добавьте раздел кнопкой ниже.")
    else:
        for idx, section in enumerate(sections):
            heading = section.get("heading") or f"Раздел {idx + 1}"
            is_active = idx == state.get("active_section_index", 0)
            cols = st.columns([0.5, 4, 0.6, 0.6, 0.6])
            with cols[0]:
                st.markdown("**▶**" if is_active else " ")
            with cols[1]:
                if st.button(
                    heading,
                    key=f"select_section_{idx}",
                    use_container_width=True,
                ):
                    state["active_section_index"] = idx
                    st.rerun()
            with cols[2]:
                if st.button("↑", key=f"up_{idx}", disabled=idx == 0):
                    sections[idx - 1], sections[idx] = sections[idx], sections[idx - 1]
                    if state.get("active_section_index") == idx:
                        state["active_section_index"] = idx - 1
                    elif state.get("active_section_index") == idx - 1:
                        state["active_section_index"] = idx
                    st.rerun()
            with cols[3]:
                if st.button(
                    "↓",
                    key=f"down_{idx}",
                    disabled=idx == len(sections) - 1,
                ):
                    sections[idx + 1], sections[idx] = sections[idx], sections[idx + 1]
                    if state.get("active_section_index") == idx:
                        state["active_section_index"] = idx + 1
                    elif state.get("active_section_index") == idx + 1:
                        state["active_section_index"] = idx
                    st.rerun()
            with cols[4]:
                if st.button("✕", key=f"del_section_{idx}"):
                    _delete_section(idx)
                    st.rerun()

    add_cols = st.columns([1, 1, 2])
    with add_cols[0]:
        if st.button("+ Раздел", key="add_section"):
            sections.append(
                {
                    "id": f"sec-{len(sections) + 1}",
                    "heading": f"Новый раздел {len(sections) + 1}",
                    "blocks": [],
                    "subsections": [],
                }
            )
            state["active_section_index"] = len(sections) - 1
            st.rerun()
    with add_cols[1]:
        if st.button("+ Список литературы", key="add_bib"):
            sections.append(
                {
                    "id": f"bib-{len(sections) + 1}",
                    "heading": "Список использованных источников",
                    "blocks": [],
                    "subsections": [],
                    "is_bibliography": True,
                    "references": [],
                }
            )
            state["active_section_index"] = len(sections) - 1
            st.rerun()


def _render_state_persistence_sidebar(state: dict[str, Any]) -> None:
    """Кнопки сохранения/загрузки JSON в sidebar.

    На текущем этапе — заглушка. Включается в отдельном коммите вместе
    с парой ``json.dumps`` / ``json.loads``.
    """
    _ = state  # пометка: state будет использован в коммите с save/load
    return


def _delete_section(idx: int) -> None:
    """Удалить раздел по индексу, корректно обновив active_section_index.

    Edge case: при удалении единственного раздела создаём пустой default,
    чтобы редактор не оказался в состоянии «нечего показывать».
    """
    state = _get_state()
    sections = state["sections"]
    if not sections:
        return
    sections.pop(idx)
    if not sections:
        sections.append(
            {
                "id": "sec-1",
                "heading": "Новый раздел",
                "blocks": [],
                "subsections": [],
            }
        )
        state["active_section_index"] = 0
        return
    active = state.get("active_section_index", 0)
    if active >= len(sections):
        state["active_section_index"] = len(sections) - 1
    elif active > idx:
        state["active_section_index"] = active - 1


# --- UI: active section editor ----------------------------------------------


def _render_active_section_editor() -> None:
    """Редактор активного раздела: heading, блоки, подразделы, references."""
    state = _get_state()
    sections = state["sections"]
    if not sections:
        return
    idx = state.get("active_section_index", 0)
    if idx < 0 or idx >= len(sections):
        idx = 0
        state["active_section_index"] = 0
    section = sections[idx]

    st.divider()
    st.subheader("Редактор раздела")

    section["heading"] = st.text_input(
        "Название раздела",
        value=section.get("heading", ""),
        key=f"edit_heading_{idx}",
    )

    if section.get("is_bibliography"):
        _render_references_editor(section, idx)
    else:
        _render_blocks_editor(section.get("blocks", []), key_prefix=f"sec{idx}")
        _render_add_block_buttons(section.get("blocks", []), key_prefix=f"sec{idx}")
        _render_subsections_editor(section, idx)


def _render_blocks_editor(blocks: list[dict[str, Any]], *, key_prefix: str) -> None:
    """Отрисовать редакторы для каждого блока списка."""
    if not blocks:
        st.caption("Блоков пока нет — добавьте кнопками ниже.")
        return
    for b_idx, block in enumerate(blocks):
        with st.expander(
            f"{b_idx + 1}. {_block_label(block)}",
            expanded=False,
        ):
            _render_single_block(block, blocks, b_idx, key_prefix=key_prefix)


def _block_label(block: dict[str, Any]) -> str:
    """Короткая метка блока для заголовка expander."""
    kind = block.get("kind", "?")
    if kind == "paragraph":
        text = block.get("text", "").strip()
        snippet = (text[:60] + "…") if len(text) > 60 else text
        return f"Параграф: {snippet or '(пусто)'}"
    if kind == "table":
        rows = block.get("rows") or []
        return f"Таблица ({len(rows)} строк)"
    if kind == "figure":
        return f"Рисунок: {block.get('caption') or '(без подписи)'}"
    if kind == "list":
        items = block.get("items") or []
        return f"Список ({len(items)} элементов)"
    if kind == "formula":
        return f"Формула: {block.get('latex') or '(пусто)'}"
    return f"Блок: {kind}"


def _render_single_block(
    block: dict[str, Any],
    blocks: list[dict[str, Any]],
    b_idx: int,
    *,
    key_prefix: str,
) -> None:
    """Отрисовать редактор одного блока + кнопку «Удалить»."""
    kind = block.get("kind")
    base = f"{key_prefix}_b{b_idx}"

    if kind == "paragraph":
        block["text"] = st.text_area(
            "Текст",
            value=block.get("text", ""),
            key=f"{base}_text",
            height=120,
        )
    elif kind == "table":
        # Простейший табличный редактор: два text_area — заголовки и строки.
        # Это сознательно низкоуровнево: data_editor в Streamlit требует
        # pandas DataFrame и непросто меняет схему при добавлении колонок.
        headers_str = ",".join(block.get("headers") or [])
        new_headers = st.text_input(
            "Заголовки (через запятую)",
            value=headers_str,
            key=f"{base}_headers",
        )
        block["headers"] = [h.strip() for h in new_headers.split(",") if h.strip()]
        rows_str = "\n".join("|".join(row) for row in (block.get("rows") or []))
        new_rows = st.text_area(
            "Строки (одна строка таблицы — одна строка ввода; ячейки разделять символом «|»)",
            value=rows_str,
            key=f"{base}_rows",
            height=140,
        )
        parsed_rows: list[list[str]] = []
        for line in new_rows.splitlines():
            if not line.strip():
                continue
            parsed_rows.append([cell.strip() for cell in line.split("|")])
        block["rows"] = parsed_rows
        block["caption"] = st.text_input(
            "Подпись таблицы",
            value=block.get("caption", ""),
            key=f"{base}_caption",
        )
    elif kind == "figure":
        block["caption"] = st.text_input(
            "Подпись рисунка",
            value=block.get("caption", ""),
            key=f"{base}_caption",
        )
        uploaded = st.file_uploader(
            "Файл изображения (PNG/JPG)",
            type=["png", "jpg", "jpeg"],
            key=f"{base}_image",
        )
        if uploaded is not None:
            # Сохраняем изображение во временный файл, чтобы экспортёр
            # смог его вставить в .docx.
            with tempfile.NamedTemporaryFile(
                suffix=Path(uploaded.name).suffix, delete=False
            ) as tmp:
                tmp.write(uploaded.getvalue())
                block["image_path"] = tmp.name
        if block.get("image_path"):
            st.caption(f"Текущий путь: `{block['image_path']}`")
    elif kind == "list":
        items_text = "\n".join(block.get("items") or [])
        new_items = st.text_area(
            "Элементы списка (по одному на строку)",
            value=items_text,
            key=f"{base}_items",
            height=140,
        )
        block["items"] = [line for line in new_items.splitlines() if line.strip()]
        block["ordered"] = st.checkbox(
            "Нумерованный список",
            value=bool(block.get("ordered", False)),
            key=f"{base}_ordered",
        )
    elif kind == "formula":
        block["latex"] = st.text_input(
            "LaTeX-код формулы",
            value=block.get("latex", ""),
            key=f"{base}_latex",
        )
        block["numbered"] = st.checkbox(
            "Нумерованная формула",
            value=bool(block.get("numbered", True)),
            key=f"{base}_numbered",
        )

    if st.button("Удалить блок", key=f"{base}_del"):
        blocks.pop(b_idx)
        st.rerun()


def _render_add_block_buttons(blocks: list[dict[str, Any]], *, key_prefix: str) -> None:
    """Кнопки «+ Параграф», «+ Таблица», «+ Рисунок», «+ Список», «+ Формула»."""
    cols = st.columns(5)
    if cols[0].button("+ Параграф", key=f"{key_prefix}_add_p"):
        blocks.append({"kind": "paragraph", "text": ""})
        st.rerun()
    if cols[1].button("+ Таблица", key=f"{key_prefix}_add_t"):
        blocks.append(
            {
                "kind": "table",
                "headers": ["Показатель", "Значение"],
                "rows": [["A", "1"], ["B", "2"]],
                "caption": "",
            }
        )
        st.rerun()
    if cols[2].button("+ Рисунок", key=f"{key_prefix}_add_f"):
        blocks.append({"kind": "figure", "image_path": "", "caption": ""})
        st.rerun()
    if cols[3].button("+ Список", key=f"{key_prefix}_add_l"):
        blocks.append({"kind": "list", "items": [], "ordered": False})
        st.rerun()
    if cols[4].button("+ Формула", key=f"{key_prefix}_add_m"):
        blocks.append({"kind": "formula", "latex": "", "numbered": True})
        st.rerun()


def _render_subsections_editor(section: dict[str, Any], sec_idx: int) -> None:
    """Список подразделов раздела с собственными блоками."""
    subs = section.setdefault("subsections", [])
    st.markdown("**Подразделы**")
    if not subs:
        st.caption("Подразделов нет.")
    for s_idx, sub in enumerate(subs):
        with st.expander(
            f"{sec_idx + 1}.{s_idx + 1} {sub.get('heading') or '(без названия)'}",
            expanded=False,
        ):
            sub["heading"] = st.text_input(
                "Название подраздела",
                value=sub.get("heading", ""),
                key=f"sub_heading_{sec_idx}_{s_idx}",
            )
            sub_blocks = sub.setdefault("blocks", [])
            _render_blocks_editor(sub_blocks, key_prefix=f"sec{sec_idx}_sub{s_idx}")
            _render_add_block_buttons(sub_blocks, key_prefix=f"sec{sec_idx}_sub{s_idx}")
            if st.button(
                "Удалить подраздел",
                key=f"del_sub_{sec_idx}_{s_idx}",
            ):
                subs.pop(s_idx)
                st.rerun()

    if st.button("+ Подраздел", key=f"add_sub_{sec_idx}"):
        subs.append(
            {
                "id": f"sub-{sec_idx}-{len(subs) + 1}",
                "heading": f"Подраздел {len(subs) + 1}",
                "blocks": [],
            }
        )
        st.rerun()


def _render_references_editor(section: dict[str, Any], sec_idx: int) -> None:
    """Редактор раздела «Список использованных источников».

    Каждая строка text_area — отдельная запись. Пустые строки
    игнорируются при сборке.
    """
    refs = section.setdefault("references", [])
    st.caption("Каждая строка — отдельный библиографический источник по ГОСТ Р 7.0.100-2018.")
    text = "\n".join(refs)
    new_text = st.text_area(
        "Список источников",
        value=text,
        height=240,
        key=f"refs_{sec_idx}",
    )
    section["references"] = [line for line in new_text.splitlines() if line.strip()]


# --- UI: generate button + preview -------------------------------------------


def _render_generate_button() -> None:
    """Кнопка генерации .docx + live-preview нарушений."""
    state = _get_state()
    st.divider()
    st.subheader("Генерация документа")
    if not (state.get("title") or "").strip():
        st.warning("Укажите название работы в sidebar — иначе документ не собрать.")
        return
    if st.button("Сгенерировать .docx", key="builder_generate"):
        try:
            data = _build_document_from_state(state)
        except Exception as exc:
            st.error(f"Не удалось сгенерировать .docx: {exc}")
            return
        st.success(f"Готово — {len(data) // 1024} КБ")
        st.download_button(
            "Скачать .docx",
            data=data,
            file_name="work.docx",
            mime=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            key="builder_download_docx",
        )
        counts = _validate_state_bytes(data, state.get("profile_id", "gost-7.32-2017"))
        total = sum(counts.values())
        if total == 0:
            st.info("Проверка профиля: нарушений не найдено")
        else:
            cols = st.columns(3)
            cols[0].metric("Ошибок", counts.get("error", 0))
            cols[1].metric("Предупр.", counts.get("warning", 0))
            cols[2].metric("Инфо", counts.get("info", 0))


# --- Public entry point -----------------------------------------------------


def render_interactive_builder() -> None:
    """Главная функция интерактивного конструктора в Streamlit.

    Порядок рендера:

    1. ``_ensure_state`` — гарантирует, что builder_state есть.
    2. Sidebar — метаданные, шаблоны, сохранение/загрузка.
    3. Дерево разделов.
    4. Редактор активного раздела.
    5. Кнопка генерации и live-preview нарушений.
    """
    _ensure_state()
    _render_sidebar_metadata()

    st.title("gostforge — конструктор работ")
    st.caption(
        "Соберите работу по ГОСТу из блоков: разделы, подразделы, "
        "параграфы, таблицы, рисунки, списки, формулы и список источников."
    )

    _render_section_tree()
    _render_active_section_editor()
    _render_generate_button()


__all__ = ["render_interactive_builder"]
