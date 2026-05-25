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

import json
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
    Citation,
    CrossRef,
    Figure,
    Formula,
    InlineElement,
    InlineFormula,
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
                "blocks": [{"kind": "paragraph", "runs": []}],
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
            if is_bib:
                # В разделе «Список ...» параграфы трактуем как ссылки.
                text = _inline_to_text(child.content)
                if text.strip():
                    references.append(text)
            else:
                # Phase 2.5: сохраняем полную inline-структуру через runs.
                # Параграф из одного «голого» TextRun сериализуется
                # одинаково и в Phase 2 (text) и в Phase 2.5 (runs).
                blocks.append(
                    {
                        "kind": "paragraph",
                        "runs": _runs_from_inline(child.content),
                    }
                )
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


# --- Inline-конвертеры (Фаза 2.5) -------------------------------------------


def _inline_to_run_dict(element: InlineElement) -> dict[str, Any]:
    """Сериализовать один InlineElement в run-dict для state.

    Формат run-dict совпадает со схемой, описанной в
    docs/phase-2.5-spec.md §4.2. Атрибуты со значением None
    в state не пишутся — это уменьшает шум JSON-save.
    """
    if isinstance(element, TextRun):
        result: dict[str, Any] = {"kind": "text", "text": element.text}
        for attr in ("bold", "italic", "underline", "superscript", "subscript"):
            value = getattr(element, attr)
            if value is not None:
                result[attr] = value
        if element.font is not None:
            result["font"] = element.font
        if element.size_pt is not None:
            result["size_pt"] = element.size_pt
        if element.color_hex is not None:
            result["color_hex"] = element.color_hex
        return result
    if isinstance(element, CrossRef):
        out: dict[str, Any] = {"kind": "xref", "target_id": element.target_id}
        if element.display_template != "{kind} {num}":
            out["display_template"] = element.display_template
        if element.prefix is not None:
            out["prefix"] = element.prefix
        return out
    if isinstance(element, InlineFormula):
        out2: dict[str, Any] = {"kind": "formula", "latex": element.latex}
        if element.id is not None:
            out2["id"] = element.id
        return out2
    if isinstance(element, Citation):
        out3: dict[str, Any] = {"kind": "citation", "source_id": element.source_id}
        if element.pages is not None:
            out3["pages"] = element.pages
        if element.template != "[{n}]":
            out3["template"] = element.template
        return out3
    # Защита от будущих типов: пишем как text-run с repr.
    return {"kind": "text", "text": str(element)}


def _run_dict_to_inline(run: dict[str, Any]) -> InlineElement | None:
    """Десериализовать run-dict в InlineElement.

    Возвращает None для невалидных/пустых run-dict-ов (например, text-run
    без поля "text"). Каллер должен игнорировать None.
    """
    kind = run.get("kind", "text")
    if kind == "text":
        text = run.get("text")
        if not isinstance(text, str):
            return None
        return TextRun(
            text=text,
            bold=_opt_bool(run.get("bold")),
            italic=_opt_bool(run.get("italic")),
            underline=_opt_bool(run.get("underline")),
            superscript=_opt_bool(run.get("superscript")),
            subscript=_opt_bool(run.get("subscript")),
            font=run.get("font") if isinstance(run.get("font"), str) else None,
            size_pt=_opt_float(run.get("size_pt")),
            color_hex=run.get("color_hex") if isinstance(run.get("color_hex"), str) else None,
        )
    if kind == "xref":
        target = run.get("target_id")
        if not isinstance(target, str) or not target:
            return None
        return CrossRef(
            target_id=target,
            display_template=run.get("display_template", "{kind} {num}"),
            prefix=run.get("prefix") if isinstance(run.get("prefix"), str) else None,
        )
    if kind == "formula":
        latex = run.get("latex")
        if not isinstance(latex, str):
            return None
        return InlineFormula(
            latex=latex,
            id=run.get("id") if isinstance(run.get("id"), str) else None,
        )
    if kind == "citation":
        source = run.get("source_id")
        if not isinstance(source, str) or not source:
            return None
        return Citation(
            source_id=source,
            pages=run.get("pages") if isinstance(run.get("pages"), str) else None,
            template=run.get("template", "[{n}]"),
        )
    return None


def _opt_bool(value: Any) -> bool | None:
    """Привести значение к bool|None для inline-атрибутов TextRun."""
    if value is None:
        return None
    return bool(value)


def _opt_float(value: Any) -> float | None:
    """Привести значение к float|None для size_pt."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _runs_from_inline(content: list[Any]) -> list[dict[str, Any]]:
    """Сериализовать Paragraph.content в список run-dict для state."""
    return [_inline_to_run_dict(el) for el in content if el is not None]


def _runs_to_inline(runs: list[dict[str, Any]]) -> list[InlineElement]:
    """Десериализовать список run-dict в list[InlineElement] для модели."""
    result: list[InlineElement] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        element = _run_dict_to_inline(run)
        if element is not None:
            result.append(element)
    return result


def _normalize_paragraph_state(block: dict[str, Any]) -> dict[str, Any]:
    """Нормализовать paragraph-блок из старого формата (text) в новый (runs).

    Старый формат Фазы 2: ``{"kind": "paragraph", "text": "..."}``
    Новый формат Фазы 2.5: ``{"kind": "paragraph", "runs": [{...}, ...]}``

    Если в блоке уже есть ``runs`` — оставляет как есть. Если есть только
    ``text`` — конвертирует его в один TextRun-dict. Если нет ни того
    ни другого — создаёт пустой ``runs = []``.

    Поле ``text`` после нормализации удаляется, чтобы single source of
    truth был только один.
    """
    if block.get("kind") != "paragraph":
        return block
    if "runs" not in block:
        text = block.get("text", "")
        if not isinstance(text, str):
            text = ""
        block["runs"] = [{"kind": "text", "text": text}] if text else []
    if "text" in block:
        del block["text"]
    return block


def _normalize_state_paragraphs(state: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно нормализовать все параграфы в state (для loaded JSON).

    Проходит по разделам и подразделам, для каждого paragraph-блока
    вызывает :func:`_normalize_paragraph_state`. Мутирует state на
    месте и возвращает его же — удобно для chained-вызовов.
    """
    for section in state.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for block in section.get("blocks") or []:
            if isinstance(block, dict):
                _normalize_paragraph_state(block)
        for sub in section.get("subsections") or []:
            if not isinstance(sub, dict):
                continue
            for block in sub.get("blocks") or []:
                if isinstance(block, dict):
                    _normalize_paragraph_state(block)
    return state


def _apply_blocks(section_builder: SectionBuilder, blocks: list[dict[str, Any]]) -> None:
    """Применить список блоков из state к SectionBuilder.

    Неизвестные типы блоков и пустые поля просто пропускаются — это
    форма «толерантного» поведения для частично заполненного state.
    """
    for block in blocks:
        kind = block.get("kind")
        if kind == "paragraph":
            # Phase 2.5: предпочитаем runs (rich), но поддерживаем
            # legacy text для обратной совместимости с Phase 2 save-ами.
            runs = block.get("runs")
            if isinstance(runs, list) and runs:
                elements = _runs_to_inline(runs)
                section_builder.rich_paragraph(elements)
            else:
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

    Студент может выгрузить текущий ``builder_state`` в .json и
    позже загрузить его обратно через file_uploader — это позволяет
    делать перерывы в работе без потери прогресса.

    Безопасность: JSON, который не является объектом с ключом
    ``sections``, отклоняется с понятной ошибкой.
    """
    st.sidebar.divider()
    st.sidebar.subheader("Сохранение / загрузка")

    # Скачать текущий state как JSON.
    state_json = json.dumps(state, ensure_ascii=False, indent=2)
    st.sidebar.download_button(
        "Скачать сохранение (.json)",
        data=state_json.encode("utf-8"),
        file_name="gostforge-builder-state.json",
        mime="application/json",
        key="builder_state_download",
    )

    # Загрузить state из JSON.
    uploaded = st.sidebar.file_uploader(
        "Загрузить сохранение (.json)",
        type=["json"],
        key="builder_state_upload",
    )
    if uploaded is not None:
        try:
            new_state = json.loads(uploaded.getvalue().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - UI feedback
            st.sidebar.error(f"Не удалось прочитать JSON: {exc}")
        else:
            if isinstance(new_state, dict) and "sections" in new_state:
                # Phase 2.5: автоматическая миграция параграфов
                # старого формата (text → runs).
                _normalize_state_paragraphs(new_state)
                st.session_state["builder_state"] = new_state
                st.sidebar.success("Состояние загружено")
                st.rerun()
            else:
                st.sidebar.error("В JSON отсутствует ключ 'sections'")


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


def _paragraph_text_only(block: dict[str, Any]) -> str:
    """Склеить только text-run-ы параграфа (для редактирования в text_area).

    inline-элементы (xref/formula/citation) намеренно пропускаются —
    их редактор появится в шаге 6.
    """
    runs = block.get("runs")
    if isinstance(runs, list):
        return "".join(
            str(r.get("text", ""))
            for r in runs
            if isinstance(r, dict) and r.get("kind", "text") == "text"
        )
    text = block.get("text")
    return str(text) if isinstance(text, str) else ""


def _extract_non_text_runs(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Вернуть все inline-элементы параграфа, кроме text-run-ов.

    Используется в UI, чтобы при редактировании текста не потерять
    уже существующие xref/formula/citation элементы.
    """
    runs = block.get("runs")
    if not isinstance(runs, list):
        return []
    return [
        r
        for r in runs
        if isinstance(r, dict) and r.get("kind", "text") != "text"
    ]


def _paragraph_preview_text(block: dict[str, Any]) -> str:
    """Вернуть видимый текст параграфа независимо от формата (text vs runs).

    Phase 2.5: для нового формата ``runs`` склеивает текст всех text-run-ов
    и подставляет placeholder-метки для inline-формул/ссылок/цитат.
    Phase 2 legacy: возвращает поле ``text`` как есть.
    """
    runs = block.get("runs")
    if isinstance(runs, list):
        parts: list[str] = []
        for run in runs:
            if not isinstance(run, dict):
                continue
            kind = run.get("kind", "text")
            if kind == "text":
                parts.append(str(run.get("text", "")))
            elif kind == "xref":
                prefix = run.get("prefix") or ""
                parts.append(f"{prefix}[→ {run.get('target_id', '?')}]")
            elif kind == "formula":
                parts.append(f"[∫ {run.get('latex', '')}]")
            elif kind == "citation":
                parts.append(f"[« {run.get('source_id', '?')}]")
        return "".join(parts)
    text = block.get("text")
    return str(text) if isinstance(text, str) else ""


def _block_label(block: dict[str, Any]) -> str:
    """Короткая метка блока для заголовка expander."""
    kind = block.get("kind", "?")
    if kind == "paragraph":
        text = _paragraph_preview_text(block).strip()
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
        # Phase 2.5: до появления полноценного inline-редактора (шаг 6)
        # параграф редактируется единым text_area; на сохранении text
        # пересобирается в один TextRun-dict, а имеющиеся inline-элементы
        # (xref/formula/citation, например, из загруженного docx)
        # сохраняются в КОНЦЕ runs и показываются readonly. Это
        # гарантирует, что мы не теряем данные между шагами 5 и 6.
        non_text_runs = _extract_non_text_runs(block)
        current_text = _paragraph_text_only(block)
        new_text = st.text_area(
            "Текст",
            value=current_text,
            key=f"{base}_text",
            height=120,
        )
        new_runs: list[dict[str, Any]] = []
        if new_text:
            new_runs.append({"kind": "text", "text": new_text})
        new_runs.extend(non_text_runs)
        block["runs"] = new_runs
        # Гарантированно убираем legacy-поле text — single source of truth.
        block.pop("text", None)
        if non_text_runs:
            st.caption(
                "В этом параграфе есть inline-элементы (формулы / ссылки / "
                "цитаты), которые сейчас не редактируются здесь, но "
                "сохраняются при пересборке .docx."
            )
            for nt in non_text_runs:
                st.code(json.dumps(nt, ensure_ascii=False), language="json")
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
        # Phase 2.5: новые параграфы создаются в формате runs.
        # UI-редактор inline-элементов появится в шаге 6; пока
        # `_render_single_block` толерантно показывает оба формата.
        blocks.append({"kind": "paragraph", "runs": []})
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
