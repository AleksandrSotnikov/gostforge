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
    # Phase 2.5: ленивая инициализация истории для undo/redo.
    if "builder_history" not in st.session_state:
        st.session_state["builder_history"] = []
    if "builder_history_cursor" not in st.session_state:
        st.session_state["builder_history_cursor"] = -1


def _get_state() -> dict[str, Any]:
    """Вернуть текущий builder_state. Перед использованием — _ensure_state()."""
    state: dict[str, Any] = st.session_state["builder_state"]
    return state


# --- Undo / Redo (Фаза 2.5) -------------------------------------------------


# Размер кольцевого буфера snapshot-ов. 50 шагов — компромисс между
# памятью (deepcopy на каждой мутации) и пользовательскими ожиданиями.
_HISTORY_LIMIT = 50


def _push_history_snapshot() -> None:
    """Сохранить текущий state в стек истории перед мутацией.

    Стек обрезается до cursor+1 (если ранее был сделан undo, любая
    новая мутация уничтожает «будущие» snapshot-ы — классический
    branch-and-truncate из текстовых редакторов). При переполнении
    стек смещается слева — старейший snapshot выпадает.
    """
    import copy

    history = st.session_state.get("builder_history") or []
    cursor = st.session_state.get("builder_history_cursor", -1)
    state = st.session_state.get("builder_state")
    if state is None:
        return
    snapshot = copy.deepcopy(state)
    # Обрезаем «redo-будущее» после cursor-а.
    truncated = list(history[: cursor + 1])
    truncated.append(snapshot)
    # Сдвигаем слева, если переполнили лимит.
    if len(truncated) > _HISTORY_LIMIT:
        truncated = truncated[-_HISTORY_LIMIT:]
    st.session_state["builder_history"] = truncated
    st.session_state["builder_history_cursor"] = len(truncated) - 1


def _undo_state() -> bool:
    """Откатиться к предыдущему snapshot. Возвращает True, если откат успешен."""
    import copy

    history = st.session_state.get("builder_history") or []
    cursor = st.session_state.get("builder_history_cursor", -1)
    if cursor <= 0:
        return False
    cursor -= 1
    st.session_state["builder_history_cursor"] = cursor
    st.session_state["builder_state"] = copy.deepcopy(history[cursor])
    return True


def _redo_state() -> bool:
    """Перейти к следующему snapshot. Возвращает True, если переход успешен."""
    import copy

    history = st.session_state.get("builder_history") or []
    cursor = st.session_state.get("builder_history_cursor", -1)
    if cursor + 1 >= len(history):
        return False
    cursor += 1
    st.session_state["builder_history_cursor"] = cursor
    st.session_state["builder_state"] = copy.deepcopy(history[cursor])
    return True


def _can_undo() -> bool:
    """Доступен ли откат назад."""
    return int(st.session_state.get("builder_history_cursor", -1)) > 0


def _can_redo() -> bool:
    """Доступен ли переход вперёд."""
    history = st.session_state.get("builder_history") or []
    cursor = int(st.session_state.get("builder_history_cursor", -1))
    return cursor + 1 < len(history)


# --- Auto-save (Фаза 2.5) ---------------------------------------------------


# Минимальный интервал между авто-сохранениями. Меньше — лишняя нагрузка
# на диск; больше — выше риск потерять прогресс.
_AUTOSAVE_INTERVAL_SEC = 30.0


def _autosave_dir() -> Path:
    """Каталог для автосохранений (~/.gostforge/autosave/).

    Создаёт каталог при необходимости. Совместим с Windows
    (``Path.home()`` отдаёт правильный путь).
    """
    path = Path.home() / ".gostforge" / "autosave"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _autosave_path() -> Path:
    """Путь к файлу автосохранения текущей сессии.

    Для MVP — одна работа за раз, имя файла фиксированное. Если в
    будущем появится мультисессия — можно перейти на session_id из
    Streamlit.
    """
    return _autosave_dir() / "last-session.json"


def _autosave_now() -> None:
    """Сохранить текущий state в autosave-файл. Не дороже одного раза в 30с.

    Ошибки IO логируются и глотаются — UI продолжает работать даже
    если диск переполнен или каталог недоступен.
    """
    import time

    last = float(st.session_state.get("builder_autosave_ts", 0.0))
    now = time.time()
    if now - last < _AUTOSAVE_INTERVAL_SEC:
        return
    try:
        state = _get_state()
        payload = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
        _autosave_path().write_bytes(payload)
        st.session_state["builder_autosave_ts"] = now
    except Exception as exc:  # pragma: no cover - не валим UI на диске
        import logging

        logging.getLogger(__name__).warning("autosave failed: %s", exc)


def _try_load_autosave_state() -> dict[str, Any] | None:
    """Прочитать autosave-файл, если он существует и свежий (<24 часов).

    Возвращает state-dict или None. Невалидный JSON, отсутствующий
    файл, устаревший файл — всё трактуется как «нет автосохранения».
    """
    import time

    path = _autosave_path()
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        if time.time() - mtime > 24 * 3600:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover - graceful degradation
        return None
    if not isinstance(data, dict) or "sections" not in data:
        return None
    return data


def _render_autosave_banner() -> None:
    """Показать баннер «обнаружено автосохранение, восстановить?» при старте UI.

    Срабатывает только если:
      * есть свежий autosave,
      * текущий state — дефолтный (т.е. пользователь не начал работу),
      * пользователь ещё не отвергал баннер в этой сессии.
    """
    if st.session_state.get("builder_autosave_dismissed"):
        return
    current = _get_state()
    # Дефолтный state — ровно тот, что выдаёт _default_state().
    if current != _default_state():
        return
    candidate = _try_load_autosave_state()
    if candidate is None:
        return
    st.info(
        "Обнаружено автосохранение предыдущей сессии. "
        "Восстановить, чтобы продолжить работу?"
    )
    cols = st.columns([1, 1, 6])
    if cols[0].button("Восстановить", key="builder_autosave_restore"):
        _normalize_state_paragraphs(candidate)
        st.session_state["builder_state"] = candidate
        st.session_state["builder_autosave_dismissed"] = True
        st.rerun()
    if cols[1].button("Игнорировать", key="builder_autosave_dismiss"):
        st.session_state["builder_autosave_dismissed"] = True
        st.rerun()


def _auto_snapshot_if_changed() -> None:
    """Записать snapshot, если state отличается от текущего в истории.

    Вызывается в начале каждого rerun. Снапшот в позиции cursor
    представляет «текущее» состояние; если state не совпал — значит
    в предыдущем rerun была мутация, и пора зафиксировать её.

    После undo/redo state выставляется равным history[cursor],
    поэтому эта функция не сделает лишнего snapshot — undo/redo
    остаются обратимыми.
    """
    state = _get_state()
    history = st.session_state.get("builder_history") or []
    cursor = int(st.session_state.get("builder_history_cursor", -1))
    if not history or cursor < 0 or cursor >= len(history):
        _push_history_snapshot()
        return
    if history[cursor] == state:
        return
    _push_history_snapshot()


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


# --- Document → state ---------------------------------------------------------


def _reconstruct_section_hierarchy(flat: list[Any]) -> list[Any]:
    """Восстановить иерархию LogicalSection из плоского списка.

    Парсер docx кладёт все секции (level 1, 2, 3, ...) в один линейный
    список ``page_section.content``. Для конструктора нужна вложенная
    структура: секция level=1 со списком children level=2, и т. д.

    Алгоритм: проходим список, поддерживая стек открытых секций.
    Каждая новая секция уровня L «закрывает» все секции со стека с
    уровнем >= L, после чего становится child-ом текущей вершины стека
    (если стек не пуст) или новой top-секцией.

    Мутирует входные LogicalSection: добавляет children. Это
    приемлемо, потому что вход — свежесозданный объект из parse_docx,
    другими частями системы не разделяемый.
    """
    from gostforge.model import LogicalSection  # noqa: PLC0415

    top: list[LogicalSection] = []
    stack: list[LogicalSection] = []
    for sec in flat:
        if not isinstance(sec, LogicalSection):
            continue
        # Не сбрасываем children: парсер уже положил туда параграфы
        # этой секции (до следующего заголовка). Мы только дополним
        # список вложенными секциями.
        # Закрываем уровни >= sec.level.
        while stack and stack[-1].level >= sec.level:
            stack.pop()
        if stack:
            stack[-1].children.append(sec)
        else:
            top.append(sec)
        stack.append(sec)
    return top


def document_to_state(document: Any) -> dict[str, Any]:
    """Разложить распарсенный Document обратно в state-dict конструктора.

    Это обратная операция к :func:`_build_document_from_state`. Используется,
    когда студент загружает чужой (или свой ранее экспортированный) .docx
    в Streamlit-конструктор и хочет продолжить редактирование.

    Маппинг:

    * ``document.metadata`` → ``state['title']`` / ``author`` / ``year`` /
      ``supervisor`` / ``organization`` / ``work_type``;
    * ``document.profile_id`` → ``state['profile_id']`` (с fallback на
      ``gost-7.32-2017``, если не задан);
    * каждый ``LogicalSection`` верхнего уровня → элемент
      ``state['sections']`` со структурой:
        - ``heading``: текст заголовка,
        - ``blocks``: list[dict] из Paragraph/Table/Figure/Formula/ListBlock,
        - ``subsections``: list[dict] для секций уровня 2,
        - ``is_bibliography``: True для раздела со списком источников,
        - ``references``: list[str] (если is_bibliography),
        - ``disabled_checks``: list[str] (фича-конструктор, для своих docx);
    * ``document.bibliography`` (если есть) сводится в один отдельный
      раздел ``is_bibliography=True``, если уже не вытащен через
      LogicalSection.

    Граничные кейсы:
    * Пустой документ → возвращается state с пустым sections-списком
      и дефолтными метаданными.
    * InlineFormula/CrossRef в параграфах сохраняются как rich-runs
      (поле ``runs`` в block-dict) — иначе при reconvert через
      ``_build_document_from_state`` они потерялись бы.
    """
    from gostforge.model import (  # noqa: PLC0415
        BibliographyEntry,
        Citation,
        CrossRef,
        Document,
        Figure,
        Formula,
        InlineFormula,
        ListBlock,
        LogicalSection,
        Paragraph,
        Table,
        TextRun,
    )

    if not isinstance(document, Document):
        raise TypeError(
            f"document_to_state ожидает Document, получено {type(document).__name__}"
        )

    metadata = document.metadata
    state: dict[str, Any] = {
        "title": metadata.title or "",
        "author": metadata.author or "",
        "supervisor": metadata.supervisor or "",
        "organization": metadata.organization or "",
        "year": metadata.year or 2026,
        "work_type": metadata.work_type or "coursework",
        "profile_id": document.profile_id or "gost-7.32-2017",
        "sections": [],
    }

    # Парсер кладёт LogicalSection плоско в page_section.content
    # (level 1, 2, 3 — все на верхнем уровне). Восстанавливаем иерархию
    # по level-у: секция level=N захватывает все следующие секции с
    # level>N как свои потомки (пока не встретится секция с level<=N).
    # Параграфы/таблицы между секциями игнорируются — builder требует,
    # чтобы каждый блок принадлежал какой-то секции.
    top_sections: list[LogicalSection] = []
    for ps in document.page_sections:
        flat = [it for it in ps.content if isinstance(it, LogicalSection)]
        # Если все секции — top-level (level==1) или плоские,
        # реконструируем иерархию по level. Если уже видим вложенные
        # секции (LogicalSection как child другой LogicalSection),
        # иерархия построена и реконструировать не надо.
        nested_section_ids: set[str] = set()
        for sec in flat:
            for child in sec.children:
                if isinstance(child, LogicalSection):
                    nested_section_ids.add(child.id)
        already_built = bool(nested_section_ids)
        if already_built:
            # Берём только секции, не являющиеся child-ом другой.
            top_sections.extend(
                [s for s in flat if s.id not in nested_section_ids]
            )
        else:
            top_sections.extend(_reconstruct_section_hierarchy(flat))

    # Эвристика для «раздела с библиографией»: заголовок попадает в
    # известный список названий («Список использованных источников»,
    # «Литература» и т. д.). Используем тот же набор алиасов, что и
    # парсер для R/B-проверок.
    bib_headings = {
        "список использованных источников",
        "список литературы",
        "литература",
        "список источников",
        "библиографический список",
    }

    def _inline_to_runs(elements: list[Any]) -> list[dict[str, Any]]:
        """Превратить inline-элементы в list[dict] (kind + поля)."""
        runs: list[dict[str, Any]] = []
        for el in elements:
            if isinstance(el, TextRun):
                run: dict[str, Any] = {"kind": "text", "text": el.text}
                if el.bold:
                    run["bold"] = True
                if el.italic:
                    run["italic"] = True
                if el.underline:
                    run["underline"] = True
                runs.append(run)
            elif isinstance(el, InlineFormula):
                runs.append({"kind": "formula", "latex": el.latex})
            elif isinstance(el, CrossRef):
                runs.append(
                    {
                        "kind": "xref",
                        "target_id": el.target_id,
                        "prefix": el.prefix or "",
                    }
                )
            elif isinstance(el, Citation):
                runs.append(
                    {
                        "kind": "citation",
                        "source_id": el.source_id,
                        "page": el.page or "",
                    }
                )
        return runs

    def _heading_text(elements: list[Any]) -> str:
        return "".join(el.text for el in elements if isinstance(el, TextRun))

    def _block_to_dict(block: Any) -> dict[str, Any] | None:
        """Один Block → dict в формате builder-state. None если не поддерживается."""
        if isinstance(block, Paragraph):
            # Если все inline — простые TextRun без форматирования, упростим
            # до text-only (для UX в обычном редакторе). Если есть xref/
            # citation/inline-formula или форматирование — runs.
            simple = all(
                isinstance(el, TextRun) and not el.bold and not el.italic and not el.underline
                for el in block.content
            )
            if simple:
                return {
                    "kind": "paragraph",
                    "text": "".join(
                        el.text for el in block.content if isinstance(el, TextRun)
                    ),
                }
            return {"kind": "paragraph", "runs": _inline_to_runs(block.content)}
        if isinstance(block, Table):
            return {
                "kind": "table",
                "headers": [_heading_text(h) for h in block.headers],
                "rows": [[_heading_text(c) for c in r] for r in block.rows],
                "caption": _heading_text(block.caption),
            }
        if isinstance(block, Figure):
            return {
                "kind": "figure",
                "image_path": block.image_path or "",
                "caption": _heading_text(block.caption),
            }
        if isinstance(block, ListBlock):
            return {
                "kind": "list",
                "ordered": block.ordered,
                "items": [_heading_text(it) for it in block.items],
            }
        if isinstance(block, Formula):
            return {
                "kind": "formula",
                "latex": block.latex or "",
                "numbered": block.number is not None,
            }
        return None

    def _section_to_state(sec: LogicalSection) -> dict[str, Any]:
        heading = _heading_text(sec.heading)
        is_bib = heading.strip().lower() in bib_headings
        out: dict[str, Any] = {
            "heading": heading,
            "blocks": [],
            "subsections": [],
            "disabled_checks": list(sec.disabled_checks),
        }
        if is_bib:
            out["is_bibliography"] = True
            out["references"] = []
        for child in sec.children:
            if isinstance(child, LogicalSection):
                # Подразделы: рекурсия только на 1 уровень (builder
                # поддерживает только subsection, не sub-subsection).
                sub_state = _section_to_state(child)
                # Подраздел не может быть библиографией.
                sub_state.pop("is_bibliography", None)
                sub_state.pop("references", None)
                out["subsections"].append(sub_state)
            else:
                bd = _block_to_dict(child)
                if bd is None:
                    continue
                # В библиографическом разделе обычные параграфы становятся
                # references.
                if is_bib and bd.get("kind") == "paragraph":
                    ref_text = bd.get("text", "")
                    if not ref_text and bd.get("runs"):
                        ref_text = "".join(
                            r.get("text", "")
                            for r in bd["runs"]
                            if r.get("kind") == "text"
                        )
                    if ref_text.strip():
                        out["references"].append(ref_text)
                else:
                    out["blocks"].append(bd)
        return out

    for sec in top_sections:
        state["sections"].append(_section_to_state(sec))

    # Если в Document есть отдельная bibliography (после _extract_bibliography),
    # но соответствующего LogicalSection-а нет в верхних — добавим.
    if document.bibliography and not any(
        s.get("is_bibliography") for s in state["sections"]
    ):
        state["sections"].append(
            {
                "heading": "Список использованных источников",
                "blocks": [],
                "subsections": [],
                "is_bibliography": True,
                "references": [
                    e.fields.get("raw", "") for e in document.bibliography
                    if isinstance(e, BibliographyEntry)
                ],
                "disabled_checks": [],
            }
        )

    return state


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
                # Рекурсия для подразделов 3-го уровня и глубже.
                for subsub in sub.get("subsections") or []:
                    subsub_builder = sub_builder.subsection(
                        subsub.get("heading", "Подраздел")
                    )
                    _apply_blocks(subsub_builder, subsub.get("blocks") or [])
            if sec.get("is_bibliography"):
                for ref in sec.get("references") or []:
                    if isinstance(ref, str) and ref.strip():
                        sec_builder.reference(ref)
            # Отключённые проверки раздела (UI: «Нормоконтроль раздела»).
            disabled = sec.get("disabled_checks") or []
            if isinstance(disabled, list) and disabled:
                if "*" in disabled:
                    sec_builder.skip_all_checks()
                else:
                    sec_builder.skip_checks(*[str(c) for c in disabled])

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        out_path = Path(tmp.name)
    # Используем экспорт напрямую, чтобы не зависеть от валидации в .save():
    # документ может быть «черновиком» с пустыми блоками — это нормально.
    document = builder.build()
    # Phase 2.5: подменяем proxy source_id у Citation на реальные
    # BibliographyEntry.id, назначенные в build().
    _resolve_citation_proxies(document, state)
    profile_id = state.get("profile_id") or document.profile_id
    profile = load_profile(profile_id)
    # Применяем style_overrides из sidebar (если заданы) поверх профиля.
    overrides = state.get("style_overrides") or {}
    profile = _apply_style_overrides(profile, overrides)
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


# --- Сбор целей для inline-редактора (Фаза 2.5) ----------------------------


def _collect_xref_targets(state: dict[str, Any]) -> list[tuple[str, str]]:
    """Собрать варианты для select-а CrossRef target_id.

    Возвращает список (value, label), где value — стабильный id вида
    ``fig-N`` / ``tbl-N`` / ``formula-N`` (совпадающий с тем, что
    генерирует WorkBuilder при сборке), а label — человекочитаемый
    «Рисунок 1: подпись».

    Нумерация по порядку обхода разделов и подразделов — она же
    воспроизводится builder-ом.
    """
    fig_n = 0
    tbl_n = 0
    formula_n = 0
    targets: list[tuple[str, str]] = []

    def _walk(blocks: list[Any]) -> None:
        nonlocal fig_n, tbl_n, formula_n
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("kind")
            if kind == "figure":
                fig_n += 1
                caption = block.get("caption") or "(без подписи)"
                targets.append((f"fig-{fig_n}", f"Рисунок {fig_n}: {caption}"))
            elif kind == "table":
                tbl_n += 1
                caption = block.get("caption") or "(без подписи)"
                targets.append((f"tbl-{tbl_n}", f"Таблица {tbl_n}: {caption}"))
            elif kind == "formula" and block.get("numbered", True):
                formula_n += 1
                latex = block.get("latex") or "(пусто)"
                preview = latex[:30] + ("…" if len(latex) > 30 else "")
                targets.append((f"formula-{formula_n}", f"Формула {formula_n}: {preview}"))

    for section in state.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if section.get("is_bibliography"):
            continue
        _walk(section.get("blocks") or [])
        for sub in section.get("subsections") or []:
            if isinstance(sub, dict):
                _walk(sub.get("blocks") or [])
    return targets


def _collect_bibliography_options(state: dict[str, Any]) -> list[tuple[str, str]]:
    """Собрать варианты для select-а Citation source_id.

    Source_id хранится в state как proxy-строка ``bib-N`` (1-based индекс
    в библиографии). При сборке документа :func:`_resolve_citation_proxies`
    конвертирует это в реальный ``BibliographyEntry.id``, который
    WorkBuilder назначил соответствующей записи.
    """
    options: list[tuple[str, str]] = []
    for section in state.get("sections") or []:
        if not isinstance(section, dict) or not section.get("is_bibliography"):
            continue
        for i, ref in enumerate(section.get("references") or [], start=1):
            if isinstance(ref, str) and ref.strip():
                snippet = ref.strip()
                if len(snippet) > 60:
                    snippet = snippet[:57] + "…"
                options.append((f"bib-{i}", f"[{i}] {snippet}"))
        break  # bibliography-раздел только один
    return options


def _resolve_citation_proxies(document: Any, state: dict[str, Any]) -> None:
    """Заменить proxy source_id вида ``bib-N`` на реальные id из bibliography.

    UI-конструктор хранит ссылки на источники как порядковые номера
    (``bib-N``), потому что реальные id назначаются только в
    ``WorkBuilder.build()`` и зависят от типа записи. После build()
    эта функция проходит по всем параграфам, ищет Citation-элементы
    с source_id вида ``bib-N`` и подставляет ``bibliography[N-1].id``.

    Mutates ``document`` in-place. Невалидные индексы оставляются как
    есть — экспортёр выдаст «[?]», что для проверки R.04 является
    корректным сигналом ошибки.
    """
    if not document.bibliography:
        return
    max_n = len(document.bibliography)

    def _patch_runs(runs: list[Any]) -> None:
        for el in runs:
            if not isinstance(el, Citation):
                continue
            sid = el.source_id
            if not sid.startswith("bib-"):
                continue
            try:
                n = int(sid[4:])
            except ValueError:
                continue
            if 1 <= n <= max_n:
                el.source_id = document.bibliography[n - 1].id

    def _walk(items: list[Any]) -> None:
        for item in items:
            if isinstance(item, Paragraph):
                _patch_runs(item.content)
            elif isinstance(item, LogicalSection):
                _walk(item.children)

    for ps in document.page_sections:
        _walk(ps.content)
    # Параметр state зарезервирован под будущие проверки (например,
    # сигнал об «осиротевших» цитатах).
    del state


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


def _render_style_overrides_section(state: dict[str, Any]) -> None:
    """Sidebar-секция «Дополнительные настройки стилей».

    Позволяет студенту переопределить ключевые визуальные параметры
    профиля для текущего документа без правки YAML. Изменения хранятся
    в ``state['style_overrides']`` как вложенный dict, при сборке
    docx применяются через :func:`_apply_style_overrides`.

    UI намеренно компактный — основные настройки (поля / шрифт /
    маркер / цвет заголовков) в одном expander.
    """
    state.setdefault("style_overrides", {})
    overrides: dict[str, Any] = state["style_overrides"]

    # Загрузим profile, чтобы показать актуальные default-значения.
    try:
        base = load_profile(state.get("profile_id", "gost-7.32-2017"))
    except Exception:  # pragma: no cover
        base = None

    if base is None:
        return  # без профиля настройки не показываем

    with st.sidebar.expander("Настройки стилей", expanded=False):
        st.caption(
            "Эти значения переопределяют параметры выбранного профиля "
            "только для текущего документа. На YAML профиля не влияют."
        )

        # --- Поля страницы ---
        st.markdown("**Поля страницы (мм)**")
        margins = overrides.setdefault("page_margins_mm", {})
        defaults = base.styles.page.margins_mm
        cols = st.columns(2)
        margins["top"] = cols[0].number_input(
            "Верх", value=int(margins.get("top", defaults.get("top", 20))),
            min_value=0, max_value=100, key="ov_margin_top",
        )
        margins["right"] = cols[1].number_input(
            "Право", value=int(margins.get("right", defaults.get("right", 15))),
            min_value=0, max_value=100, key="ov_margin_right",
        )
        margins["bottom"] = cols[0].number_input(
            "Низ", value=int(margins.get("bottom", defaults.get("bottom", 20))),
            min_value=0, max_value=100, key="ov_margin_bottom",
        )
        margins["left"] = cols[1].number_input(
            "Лево", value=int(margins.get("left", defaults.get("left", 30))),
            min_value=0, max_value=100, key="ov_margin_left",
        )

        # --- Основной текст ---
        st.markdown("**Основной текст**")
        overrides["body_font"] = st.text_input(
            "Шрифт",
            value=overrides.get("body_font", base.styles.body.font),
            key="ov_body_font",
        )
        cols = st.columns(2)
        overrides["body_size_pt"] = cols[0].number_input(
            "Кегль (pt)",
            value=float(overrides.get("body_size_pt", base.styles.body.size_pt)),
            min_value=8.0, max_value=24.0, step=0.5, key="ov_body_size",
        )
        overrides["body_line_spacing"] = cols[1].number_input(
            "Межстрочный",
            value=float(overrides.get("body_line_spacing", base.styles.body.line_spacing)),
            min_value=1.0, max_value=3.0, step=0.1, key="ov_line_spacing",
        )
        overrides["body_first_line_indent_cm"] = st.number_input(
            "Отступ первой строки (см)",
            value=float(overrides.get(
                "body_first_line_indent_cm", base.styles.body.first_line_indent_cm
            )),
            min_value=0.0, max_value=3.0, step=0.05, key="ov_indent",
        )

        # --- Заголовки ---
        st.markdown("**Заголовки**")
        overrides["heading1_uppercase"] = st.checkbox(
            "Глава 1 — ВЕРХНИЙ РЕГИСТР",
            value=bool(overrides.get(
                "heading1_uppercase", base.styles.heading_1.uppercase
            )),
            key="ov_h1_upper",
        )
        overrides["heading1_color"] = st.text_input(
            "Цвет (auto или RRGGBB)",
            value=overrides.get("heading1_color", base.styles.heading_1.color),
            help="auto = чёрный (по ГОСТу). Hex без # — например, 000000.",
            key="ov_h1_color",
        )
        cols = st.columns(2)
        overrides["heading1_spacing_before_pt"] = cols[0].number_input(
            "Отступ до (pt)",
            value=float(overrides.get(
                "heading1_spacing_before_pt", base.styles.heading_1.spacing_before_pt
            )),
            min_value=0.0, max_value=72.0, step=1.0, key="ov_h1_before",
        )
        overrides["heading1_spacing_after_pt"] = cols[1].number_input(
            "Отступ после (pt)",
            value=float(overrides.get(
                "heading1_spacing_after_pt", base.styles.heading_1.spacing_after_pt
            )),
            min_value=0.0, max_value=72.0, step=1.0, key="ov_h1_after",
        )

        # --- Списки ---
        st.markdown("**Списки**")
        overrides["bullet_char"] = st.text_input(
            "Маркер",
            value=overrides.get("bullet_char", base.styles.lists.bullet_char),
            help="Один символ: – (тире по ГОСТ), •, *, ◦, →",
            key="ov_bullet",
        )
        overrides["ordered_format"] = st.text_input(
            "Шаблон нумерации",
            value=overrides.get("ordered_format", base.styles.lists.ordered_format),
            help="Используйте {n} для подстановки номера. Примеры: «{n})», «{n}.», «{n}.».",
            key="ov_ordered",
        )

        # --- Таблицы ---
        st.markdown("**Таблицы**")
        border_options = ["single", "double", "dashed", "dotted", "none"]
        current_border = overrides.get(
            "table_border_style", base.styles.table.border_style
        )
        overrides["table_border_style"] = st.selectbox(
            "Стиль рамки",
            options=border_options,
            index=border_options.index(current_border)
            if current_border in border_options
            else 0,
            key="ov_tbl_border",
        )
        overrides["table_header_bold"] = st.checkbox(
            "Жирная шапка",
            value=bool(overrides.get(
                "table_header_bold", base.styles.table.header_bold
            )),
            key="ov_tbl_bold",
        )

        # --- Сброс ---
        if st.button("Сбросить все настройки стилей", key="ov_reset"):
            state["style_overrides"] = {}
            st.rerun()


def _apply_style_overrides(profile: Any, overrides: dict[str, Any]) -> Any:
    """Применить style_overrides из state к копии профиля.

    Возвращает новый Profile (через model_copy) — оригинал не меняется.
    Если overrides пустой — возвращает исходный профиль без копирования.
    """
    if not overrides:
        return profile
    p = profile.model_copy(deep=True)
    # Поля страницы.
    margins = overrides.get("page_margins_mm") or {}
    if margins:
        for side in ("top", "right", "bottom", "left"):
            if side in margins:
                p.styles.page.margins_mm[side] = float(margins[side])
    # Тело.
    if "body_font" in overrides and overrides["body_font"]:
        p.styles.body.font = overrides["body_font"]
    if "body_size_pt" in overrides:
        p.styles.body.size_pt = float(overrides["body_size_pt"])
    if "body_line_spacing" in overrides:
        p.styles.body.line_spacing = float(overrides["body_line_spacing"])
    if "body_first_line_indent_cm" in overrides:
        p.styles.body.first_line_indent_cm = float(
            overrides["body_first_line_indent_cm"]
        )
    # Заголовок 1.
    if "heading1_uppercase" in overrides:
        p.styles.heading_1.uppercase = bool(overrides["heading1_uppercase"])
    if "heading1_color" in overrides and overrides["heading1_color"]:
        p.styles.heading_1.color = overrides["heading1_color"]
    if "heading1_spacing_before_pt" in overrides:
        p.styles.heading_1.spacing_before_pt = float(
            overrides["heading1_spacing_before_pt"]
        )
    if "heading1_spacing_after_pt" in overrides:
        p.styles.heading_1.spacing_after_pt = float(
            overrides["heading1_spacing_after_pt"]
        )
    # Списки.
    if "bullet_char" in overrides and overrides["bullet_char"]:
        p.styles.lists.bullet_char = overrides["bullet_char"]
    if "ordered_format" in overrides and overrides["ordered_format"]:
        p.styles.lists.ordered_format = overrides["ordered_format"]
    # Таблицы.
    if "table_border_style" in overrides:
        p.styles.table.border_style = overrides["table_border_style"]
    if "table_header_bold" in overrides:
        p.styles.table.header_bold = bool(overrides["table_header_bold"])
    return p


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

    _render_style_overrides_section(state)

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


def _highlight_query_in_text(text: str, query: str) -> str:
    """Обернуть все вхождения query в <mark> для подсветки в Streamlit-caption.

    Сохраняет регистр найденного фрагмента (case-insensitive match,
    но в результате — оригинальный регистр). HTML-инъекции защищены
    через html.escape ВСЕГО входного text, потом мы НЕ экранируем
    <mark>...</mark> теги — они стандартные.
    """
    if not query:
        return text
    import html  # noqa: PLC0415
    import re  # noqa: PLC0415

    escaped_text = html.escape(text)
    # Регекс по escape-нутому text, но ищем escape-нутый query —
    # чтобы не сломаться на спец-символах.
    escaped_query = re.escape(html.escape(query))
    pattern = re.compile(escaped_query, re.IGNORECASE)
    return pattern.sub(
        lambda m: f"<mark>{m.group(0)}</mark>", escaped_text
    )


def _section_matches_query(section: dict[str, Any], query: str) -> bool:
    """True, если в разделе (или его подразделах/блоках) есть совпадение
    с поисковым запросом (case-insensitive substring).

    Ищет в:
    * заголовке раздела, подразделов, sub-subsections;
    * текстах параграфов (включая rich-формат с runs);
    * подписях таблиц / рисунков;
    * элементах списков;
    * текстах ссылок (references).
    """
    if not query:
        return True

    def text_in_block(b: dict[str, Any]) -> str:
        kind = b.get("kind", "")
        text = b.get("text", "")
        if not text and b.get("runs"):
            text = "".join(
                r.get("text", "") for r in b["runs"] if r.get("kind") == "text"
            )
        if kind == "table":
            text += " " + str(b.get("caption", ""))
            for row in b.get("rows", []):
                text += " " + " ".join(str(c) for c in row)
            text += " " + " ".join(str(h) for h in b.get("headers", []))
        elif kind == "figure":
            text += " " + str(b.get("caption", ""))
        elif kind == "list":
            text += " " + " ".join(str(it) for it in b.get("items", []))
        return text

    def search_in_section(sec: dict[str, Any]) -> bool:
        if query in str(sec.get("heading", "")).lower():
            return True
        for b in sec.get("blocks", []) or []:
            if query in text_in_block(b).lower():
                return True
        for ref in sec.get("references") or []:
            if query in str(ref).lower():
                return True
        for sub in sec.get("subsections") or []:
            if search_in_section(sub):
                return True
        return False

    return search_in_section(section)


def _render_section_tree() -> None:
    """Список разделов с кнопками ↑/↓/⎘/✕ и фильтром-поиском."""
    state = _get_state()
    sections = state["sections"]

    st.subheader("Разделы работы")

    # Поиск по разделам: фильтрует и подсвечивает в дереве.
    # Хранится в state, чтобы переживать rerun.
    query = st.text_input(
        "Поиск по разделам",
        value=str(state.get("section_search", "")),
        placeholder="часть заголовка или текста параграфа",
        key="section_search_input",
        help=(
            "Фильтрует список ниже. Совпадения ищутся в заголовках разделов, "
            "подразделов и текстах параграфов (регистронезависимо)."
        ),
    )
    state["section_search"] = query
    filter_q = query.strip().lower()

    matched: set[int] = set()
    if filter_q:
        for idx, sec in enumerate(sections):
            if _section_matches_query(sec, filter_q):
                matched.add(idx)
        if not matched:
            st.warning(f"Ничего не найдено по запросу «{query}»")

    if not sections:
        st.info("Нет ни одного раздела. Добавьте раздел кнопкой ниже.")
    else:
        for idx, section in enumerate(sections):
            # Если активен фильтр и текущий раздел не совпал — скрываем.
            if filter_q and idx not in matched:
                continue
            heading = section.get("heading") or f"Раздел {idx + 1}"
            is_active = idx == state.get("active_section_index", 0)
            # 6 колонок: маркер активного, заголовок, ↑, ↓, дубль, удалить.
            cols = st.columns([0.5, 4, 0.6, 0.6, 0.6, 0.6])
            with cols[0]:
                st.markdown("**▶**" if is_active else " ")
            with cols[1]:
                # Подсветка совпадения query в heading.
                button_label = heading
                if filter_q:
                    # Streamlit button не рендерит markdown — поэтому
                    # подсветку показываем рядом отдельным caption-ом.
                    if st.button(
                        button_label,
                        key=f"select_section_{idx}",
                        use_container_width=True,
                    ):
                        state["active_section_index"] = idx
                        st.rerun()
                    st.caption(
                        _highlight_query_in_text(heading, filter_q),
                        unsafe_allow_html=True,
                    )
                else:
                    if st.button(
                        button_label,
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
                if st.button(
                    "⎘",
                    key=f"dup_{idx}",
                    help="Дублировать раздел",
                ):
                    _duplicate_section(idx)
                    st.rerun()
            with cols[5]:
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


# Готовые шаблоны разделов для быстрой вставки. Ключ = id, значение =
# (label, фабрика → dict с heading/blocks). Используются в UI-кнопках
# «+ Раздел из шаблона».
_SECTION_TEMPLATES: dict[str, tuple[str, Any]] = {
    "intro": (
        "Введение",
        lambda: {
            "heading": "Введение",
            "blocks": [
                {"kind": "paragraph", "text": "Актуальность темы исследования..."},
                {"kind": "paragraph", "text": "Цель работы — ..."},
                {"kind": "paragraph", "text": "Задачи работы:"},
                {
                    "kind": "list",
                    "ordered": True,
                    "items": ["задача 1", "задача 2", "задача 3"],
                },
            ],
        },
    ),
    "conclusion": (
        "Заключение",
        lambda: {
            "heading": "Заключение",
            "blocks": [
                {
                    "kind": "paragraph",
                    "text": "В ходе работы достигнуты следующие результаты...",
                }
            ],
        },
    ),
    "abstract": (
        "Реферат",
        lambda: {
            "heading": "Реферат",
            "blocks": [
                {
                    "kind": "paragraph",
                    "text": (
                        "Работа объёмом N страниц содержит N рисунков, N таблиц, "
                        "N источников. Ключевые слова: ..."
                    ),
                }
            ],
        },
    ),
    "toc": (
        "Содержание",
        lambda: {
            "heading": "Содержание",
            "blocks": [
                {"kind": "paragraph", "text": "Содержание формируется автоматически."},
            ],
        },
    ),
    "bib": (
        "Список использованных источников",
        lambda: {
            "heading": "Список использованных источников",
            "blocks": [],
            "is_bibliography": True,
            "references": [],
        },
    ),
    "appendix": (
        "Приложение А",
        lambda: {
            "heading": "Приложение А",
            "blocks": [{"kind": "paragraph", "text": "Текст приложения..."}],
            "disabled_checks": ["*"],  # приложения — не по ГОСТу
        },
    ),
    "chapter": (
        "Глава N",
        lambda: {
            "heading": "Глава 1. Название главы",
            "blocks": [{"kind": "paragraph", "text": ""}],
            "subsections": [
                {
                    "heading": "1.1 Подраздел",
                    "blocks": [{"kind": "paragraph", "text": ""}],
                }
            ],
        },
    ),
}


def _render_section_templates_sidebar() -> None:
    """Sidebar-блок: «+ Раздел из шаблона» — быстрая вставка готовых разделов.

    Выпадающий список с шаблонами + кнопка «Вставить» добавляет
    раздел в конец state['sections'] и переключает активный.
    """
    st.sidebar.markdown("---")
    st.sidebar.subheader("Раздел из шаблона")
    options = list(_SECTION_TEMPLATES.keys())
    sel = st.sidebar.selectbox(
        "Шаблон",
        options=options,
        format_func=lambda k: _SECTION_TEMPLATES[k][0],
        key="section_template_pick",
    )
    if st.sidebar.button("+ Вставить раздел", key="insert_section_template"):
        state = _get_state()
        _, factory = _SECTION_TEMPLATES[sel]
        new_section = factory()
        state["sections"].append(new_section)
        state["active_section_index"] = len(state["sections"]) - 1
        st.rerun()


def _render_bulk_operations_sidebar() -> None:
    """Sidebar-блок: bulk-операции над всеми разделами.

    Доступно:
    * «Удалить пустые параграфы» — у всех разделов выбрасывает блоки
      kind='paragraph' с пустым text/runs.
    * «Заголовки в Title Case» — приводит heading-и всех разделов
      к виду «Первое Слово Каждого Слова».
    * «Сбросить все skip-checks» — очищает disabled_checks у всех
      разделов.
    """
    state = _get_state()
    if not state.get("sections"):
        return
    st.sidebar.markdown("---")
    st.sidebar.subheader("Массовые операции")

    if st.sidebar.button(
        "Удалить пустые параграфы",
        key="bulk_remove_empty",
        help="Из всех разделов выбрасывает блоки kind='paragraph' "
        "с пустым text/runs.",
    ):
        removed = _bulk_remove_empty_paragraphs(state)
        if removed > 0:
            st.sidebar.success(f"Удалено пустых параграфов: {removed}")
        else:
            st.sidebar.info("Пустых параграфов не найдено")
        st.rerun()

    if st.sidebar.button(
        "Заголовки в Title Case",
        key="bulk_title_case",
        help="Привести все заголовки разделов к виду «Каждое Слово С Заглавной».",
    ):
        changed = _bulk_apply_title_case(state)
        st.sidebar.success(f"Изменено заголовков: {changed}")
        st.rerun()

    if st.sidebar.button(
        "Сбросить все skip-checks",
        key="bulk_reset_skip",
        help="Очищает disabled_checks у всех разделов (включить нормоконтроль везде).",
    ):
        reset = _bulk_reset_disabled_checks(state)
        st.sidebar.info(f"Снято отключений у {reset} разделов")
        st.rerun()

    if st.sidebar.button(
        "Авто-нумерация глав и подразделов",
        key="bulk_autonumber",
        help=(
            "Проставляет «1.», «1.1», «1.1.1» перед каждым "
            "заголовком в работе. Существующая нумерация будет "
            "заменена. Структурные разделы (Введение, Заключение, "
            "Содержание, Реферат, Список источников, Приложения) "
            "пропускаются."
        ),
    ):
        numbered = _bulk_auto_number_headings(state)
        st.sidebar.success(f"Пронумеровано заголовков: {numbered}")
        st.rerun()


def _bulk_remove_empty_paragraphs(state: dict[str, Any]) -> int:
    """Удалить пустые параграфы во всех разделах. Возвращает счётчик."""
    removed = 0
    for sec in state.get("sections", []):
        removed += _remove_empty_in_blocks(sec.get("blocks") or [])
        for sub in sec.get("subsections") or []:
            removed += _remove_empty_in_blocks(sub.get("blocks") or [])
            for subsub in sub.get("subsections") or []:
                removed += _remove_empty_in_blocks(subsub.get("blocks") or [])
    return removed


def _remove_empty_in_blocks(blocks: list[dict[str, Any]]) -> int:
    """Мутирует blocks: удаляет пустые параграфы, возвращает счётчик."""
    removed = 0
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.get("kind") != "paragraph":
            i += 1
            continue
        text = b.get("text", "")
        if not text and b.get("runs"):
            text = "".join(
                r.get("text", "") for r in b["runs"] if r.get("kind") == "text"
            )
        if not text.strip():
            blocks.pop(i)
            removed += 1
        else:
            i += 1
    return removed


def _bulk_apply_title_case(state: dict[str, Any]) -> int:
    """Привести все heading-и к Title Case. Возвращает счётчик изменённых."""
    changed = 0
    for sec in state.get("sections", []):
        old = sec.get("heading", "")
        new = _to_title_case(old)
        if new != old:
            sec["heading"] = new
            changed += 1
        for sub in sec.get("subsections") or []:
            old = sub.get("heading", "")
            new = _to_title_case(old)
            if new != old:
                sub["heading"] = new
                changed += 1
            for subsub in sub.get("subsections") or []:
                old = subsub.get("heading", "")
                new = _to_title_case(old)
                if new != old:
                    subsub["heading"] = new
                    changed += 1
    return changed


def _to_title_case(text: str) -> str:
    """Title case с учётом русского: «введение» → «Введение»,
    «глава 1. анализ» → «Глава 1. Анализ».

    Стандартный str.title() ломается на апострофах и цифрах, поэтому
    делаем сами через split-capitalize-join, сохраняя ведущие/конечные
    пробелы и разделители.
    """
    if not text:
        return text
    words = text.split(" ")
    out: list[str] = []
    for w in words:
        if w:
            # capitalize() ставит остальные в lower — это плохо для
            # «1.1». Делаем: первая буква UP, остальные как есть.
            out.append(w[0].upper() + w[1:] if w[0].isalpha() else w)
        else:
            out.append(w)
    return " ".join(out)


# Заголовки, которые НЕ нужно автонумеровать (это структурные разделы
# по ГОСТу — у них нет номера). Сравнение case-insensitive по нормализованной
# первой строке без существующей нумерации.
_STRUCTURAL_HEADINGS = frozenset(
    {
        "введение",
        "заключение",
        "содержание",
        "реферат",
        "список использованных источников",
        "список литературы",
        "литература",
        "список источников",
        "библиографический список",
        "оглавление",
        "перечень сокращений",
        "перечень обозначений и сокращений",
    }
)


def _is_structural_heading(heading: str) -> bool:
    """True, если заголовок — структурный (Введение, Заключение, ...)
    или приложение (начинается с «Приложение»)."""
    import re  # noqa: PLC0415

    # Снимаем существующую нумерацию вида '1 Х', '1. Х', '1.1 Х' для
    # сравнения с базовым названием.
    cleaned = re.sub(r"^\d+(\.\d+)*\.?\s+", "", heading).strip().lower()
    if cleaned in _STRUCTURAL_HEADINGS:
        return True
    # Приложения: «Приложение А», «Приложение Б», ...
    if cleaned.startswith("приложение"):
        return True
    return False


def _strip_existing_number(heading: str) -> str:
    """Убрать существующую нумерацию из начала heading.

    Примеры: «1 Глава» → «Глава», «1.1. Подраздел» → «Подраздел»,
    «1.1.1 Пункт» → «Пункт». Если номера нет — возвращает как есть.
    """
    import re  # noqa: PLC0415

    return re.sub(r"^\d+(\.\d+)*\.?\s+", "", heading).strip()


def _bulk_auto_number_headings(state: dict[str, Any]) -> int:
    """Проставить «1», «1.1», «1.1.1» перед заголовками не-структурных
    разделов. Возвращает счётчик пронумерованных.

    Алгоритм:
    1. Идём по top-level sections. Если структурный — пропускаем,
       счётчик top не растёт.
    2. Иначе top-counter++, heading = «N <название>».
    3. Рекурсивно для subsections и sub-subsections, поддерживая
       префикс родителя.
    """
    counter = 0
    top_idx = 0
    for sec in state.get("sections") or []:
        if _is_structural_heading(sec.get("heading", "")):
            # Заодно нормализуем — убираем случайную нумерацию.
            base = _strip_existing_number(sec.get("heading", ""))
            if base != sec.get("heading", ""):
                sec["heading"] = base
            # Подразделы внутри структурного раздела всё равно нумеруем,
            # но без top-уровневого префикса.
            for sub in sec.get("subsections") or []:
                sub["heading"] = _strip_existing_number(sub.get("heading", ""))
            continue
        top_idx += 1
        base = _strip_existing_number(sec.get("heading", ""))
        sec["heading"] = f"{top_idx} {base}"
        counter += 1
        for s_idx, sub in enumerate(sec.get("subsections") or [], start=1):
            sub_base = _strip_existing_number(sub.get("heading", ""))
            sub["heading"] = f"{top_idx}.{s_idx} {sub_base}"
            counter += 1
            for ss_idx, subsub in enumerate(
                sub.get("subsections") or [], start=1
            ):
                ss_base = _strip_existing_number(subsub.get("heading", ""))
                subsub["heading"] = f"{top_idx}.{s_idx}.{ss_idx} {ss_base}"
                counter += 1
    return counter


def _bulk_reset_disabled_checks(state: dict[str, Any]) -> int:
    """Очистить disabled_checks у всех разделов. Возвращает счётчик."""
    reset = 0
    for sec in state.get("sections", []):
        if sec.get("disabled_checks"):
            sec["disabled_checks"] = []
            reset += 1
    return reset


def _render_state_persistence_sidebar(state: dict[str, Any]) -> None:
    """Кнопки сохранения/загрузки JSON в sidebar.

    Студент может выгрузить текущий ``builder_state`` в .json и
    позже загрузить его обратно через file_uploader — это позволяет
    делать перерывы в работе без потери прогресса.

    Безопасность: JSON, который не является объектом с ключом
    ``sections``, отклоняется с понятной ошибкой.
    """
    st.sidebar.divider()
    st.sidebar.subheader("История")
    undo_col, redo_col = st.sidebar.columns(2)
    undo_disabled = not _can_undo()
    redo_disabled = not _can_redo()
    if undo_col.button("⟲ Отменить", disabled=undo_disabled, key="builder_undo"):
        if _undo_state():
            st.rerun()
    if redo_col.button("⟳ Повторить", disabled=redo_disabled, key="builder_redo"):
        if _redo_state():
            st.rerun()
    history = st.session_state.get("builder_history") or []
    cursor = int(st.session_state.get("builder_history_cursor", -1))
    st.sidebar.caption(f"Snapshot {cursor + 1} из {len(history)}")

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

    # Загрузить готовую работу .docx и разложить в конструктор.
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Загрузить готовую работу (.docx) и разложить её в конструктор "
        "для дальнейшего редактирования"
    )
    docx_uploaded = st.sidebar.file_uploader(
        "Загрузить .docx в конструктор",
        type=["docx"],
        key="builder_docx_import",
    )
    if docx_uploaded is not None:
        _handle_docx_import(docx_uploaded.getvalue(), docx_uploaded.name)


def _handle_docx_import(data: bytes, filename: str) -> None:
    """Распарсить загруженный .docx и загрузить как builder-state.

    Использует parse_docx → document_to_state. Если парсинг или
    преобразование падает — показывает st.error и не трогает текущий
    state (защищаемся от потери работы).

    После успешной загрузки сразу прогоняет нормоконтроль через
    profile из state и показывает summary нарушений — пользователь
    получает мгновенный feedback о том, что нужно исправить.
    """
    from gostforge.parser import parse_docx  # noqa: PLC0415

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".docx", delete=False
        ) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        document = parse_docx(tmp_path)
        new_state = document_to_state(document)
    except Exception as exc:  # pragma: no cover - UI feedback
        st.sidebar.error(f"Не удалось разложить «{filename}»: {exc}")
        return

    if not new_state.get("sections"):
        st.sidebar.warning(
            f"В «{filename}» не нашлось ни одного раздела. "
            "Возможно, работа без заголовков 1-го уровня."
        )
        return

    _normalize_state_paragraphs(new_state)
    st.session_state["builder_state"] = new_state

    # Если в импортируемом docx есть комментарии рецензента (от
    # научного руководителя в Word) — сохраняем их в session_state
    # для отдельной панели отображения. document_to_state их не
    # переносит в state, потому что в builder-state нет такого поля.
    parsed_comments = getattr(document, "comments", None) or []
    if parsed_comments:
        st.session_state["last_imported_comments"] = [
            {
                "id": c.id,
                "author": c.author,
                "date": c.date,
                "text": c.text,
            }
            for c in parsed_comments
        ]

    # Сохраним сводку для пользователя: сколько и каких нарушений
    # нашёл нормоконтроль (показывается через _render_import_violations_panel
    # после rerun, потому что прямой st.* здесь не дойдёт в main-области).
    summary = _compute_import_violations_summary(document, new_state["profile_id"])
    st.session_state["last_import_summary"] = {
        "filename": filename,
        "sections_count": len(new_state["sections"]),
        **summary,
    }

    st.sidebar.success(
        f"«{filename}» загружен в конструктор: "
        f"{len(new_state['sections'])} разделов, "
        f"{summary['total']} нарушений нормоконтроля."
    )
    st.rerun()


def _compute_import_violations_summary(
    document: Any, profile_id: str
) -> dict[str, Any]:
    """Прогон нормоконтроля для импортируемого документа.

    Возвращает {'total', 'by_severity', 'top_codes'} — компактный
    summary для UI. На случай ошибок (профиль не найден, exception
    внутри validate) возвращает пустую сводку.
    """
    from collections import Counter  # noqa: PLC0415

    try:
        profile = load_profile(profile_id)
        violations = validate(document, profile)
    except Exception:  # noqa: BLE001
        return {"total": 0, "by_severity": {}, "top_codes": []}
    by_severity: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for v in violations:
        if v.severity in by_severity:
            by_severity[v.severity] += 1
    codes = Counter(v.check_code for v in violations).most_common(10)
    return {
        "total": len(violations),
        "by_severity": by_severity,
        "top_codes": [{"code": c, "count": n} for c, n in codes],
    }


def _compute_progress_metrics(state: dict[str, Any]) -> dict[str, Any]:
    """Подсчитать метрики прогресса работы по state.

    Возвращает:
    * sections_total, sections_filled (с непустым контентом),
    * paragraphs_total, paragraphs_nonempty,
    * tables, figures, formulas, list_items,
    * references_total,
    * total_words в текстах параграфов.

    Используется в _render_progress_panel.
    """
    out = {
        "sections_total": 0,
        "sections_filled": 0,
        "paragraphs_total": 0,
        "paragraphs_nonempty": 0,
        "tables": 0,
        "figures": 0,
        "formulas": 0,
        "list_items": 0,
        "references_total": 0,
        "total_words": 0,
    }

    def block_text(b: dict[str, Any]) -> str:
        text = b.get("text", "")
        if not text and b.get("runs"):
            text = "".join(
                r.get("text", "")
                for r in b["runs"]
                if r.get("kind") == "text"
            )
        return text

    def walk_section(sec: dict[str, Any]) -> bool:
        """Возвращает True если в секции есть контент."""
        has_content = False
        for b in sec.get("blocks", []) or []:
            kind = b.get("kind", "")
            if kind == "paragraph":
                out["paragraphs_total"] += 1
                t = block_text(b)
                if t.strip():
                    out["paragraphs_nonempty"] += 1
                    out["total_words"] += len(t.split())
                    has_content = True
            elif kind == "table":
                out["tables"] += 1
                has_content = True
            elif kind == "figure":
                out["figures"] += 1
                has_content = True
            elif kind == "formula":
                out["formulas"] += 1
                has_content = True
            elif kind == "list":
                out["list_items"] += len(b.get("items") or [])
                has_content = True
        if sec.get("is_bibliography"):
            refs = sec.get("references") or []
            out["references_total"] += len(refs)
            if refs:
                has_content = True
        for sub in sec.get("subsections") or []:
            if walk_section(sub):
                has_content = True
        return has_content

    for sec in state.get("sections", []) or []:
        out["sections_total"] += 1
        if walk_section(sec):
            out["sections_filled"] += 1

    return out


def _render_progress_panel() -> None:
    """Показать прогресс работы: заполненность разделов, число слов и пр.

    Отображается перед деревом разделов. Помогает студенту видеть
    общую картину: сколько разделов уже наполнено, сколько слов
    написано, сколько таблиц/рисунков/источников.
    """
    state = _get_state()
    if not state.get("sections"):
        return
    metrics = _compute_progress_metrics(state)
    total = metrics["sections_total"]
    filled = metrics["sections_filled"]
    if total > 0:
        progress = filled / total
    else:
        progress = 0.0

    with st.expander(
        f"Прогресс работы — {filled}/{total} разделов заполнено "
        f"({metrics['total_words']} слов)",
        expanded=False,
    ):
        st.progress(progress)
        cols = st.columns(4)
        cols[0].metric("Параграфы", metrics["paragraphs_nonempty"])
        cols[1].metric("Таблицы", metrics["tables"])
        cols[2].metric("Рисунки", metrics["figures"])
        cols[3].metric("Источники", metrics["references_total"])
        cols2 = st.columns(4)
        cols2[0].metric("Формулы", metrics["formulas"])
        cols2[1].metric("Элементы списков", metrics["list_items"])
        cols2[2].metric("Слов всего", metrics["total_words"])
        # Кол-во знаков по словам приближённое: ~6 знаков на слово
        # (среднее для русского текста). Используется только для
        # быстрой оценки объёма.
        est_chars = metrics["total_words"] * 6
        cols2[3].metric("Знаков (≈)", est_chars)


def _render_imported_comments_panel() -> None:
    """Показать комментарии рецензента, импортированные из docx.

    Если научный руководитель оставил замечания через Word
    (комментарии в правой панели), они извлекаются парсером и
    показываются здесь. Студент видит их в одном месте — это
    удобнее, чем переключаться между конструктором и Word.
    """
    comments = st.session_state.get("last_imported_comments")
    if not comments:
        return
    with st.expander(
        f"Комментарии рецензента из импортированной работы — "
        f"{len(comments)} шт.",
        expanded=False,
    ):
        for c in comments:
            author = c.get("author", "?")
            date = (c.get("date") or "").split("T")[0]
            text = c.get("text", "")
            st.markdown(f"**{author}** ({date}):")
            st.write(text)
            st.divider()
        if st.button("Скрыть комментарии", key="dismiss_comments"):
            del st.session_state["last_imported_comments"]
            st.rerun()


def _render_import_violations_panel() -> None:
    """Показать summary нарушений после import-docx (если был).

    Рендерится в main-области (не в sidebar), потому что место
    в sidebar очень ограничено. Появляется один раз — при следующем
    rerun сводка остаётся (пользователь может прочитать), но новых
    нарушений не показывает.
    """
    summary = st.session_state.get("last_import_summary")
    if not summary:
        return
    total = summary.get("total", 0)
    if total == 0:
        st.success(
            f"Импорт «{summary['filename']}» прошёл без нарушений нормоконтроля."
        )
        if st.button("Скрыть сводку импорта", key="dismiss_import_summary"):
            del st.session_state["last_import_summary"]
            st.rerun()
        return

    with st.expander(
        f"Нормоконтроль импортированной работы «{summary['filename']}» — "
        f"{total} нарушений",
        expanded=True,
    ):
        by_sev = summary.get("by_severity", {})
        cols = st.columns(3)
        cols[0].metric("Ошибки", by_sev.get("error", 0))
        cols[1].metric("Предупреждения", by_sev.get("warning", 0))
        cols[2].metric("Информация", by_sev.get("info", 0))

        top = summary.get("top_codes", [])
        if top:
            st.markdown("**Топ-10 нарушений:**")
            for entry in top:
                st.write(f"- `{entry['code']}` × {entry['count']}")

        # Кнопка автофиксов: применить fixer к текущему state и
        # обновить summary. Доступно только если есть фиксеры
        # под найденные нарушения.
        from gostforge.fixer.engine import registered_fixers  # noqa: PLC0415

        fixable_codes = set(registered_fixers()) & {
            e["code"] for e in top
        }
        if fixable_codes:
            st.markdown("---")
            st.caption(
                f"Доступны автофиксы для кодов: {', '.join(sorted(fixable_codes))}. "
                "Кнопка применит их к загруженному документу и пересчитает сводку."
            )
            if st.button(
                "Применить автофиксы",
                key="apply_autofixes",
                type="primary",
            ):
                _apply_autofixes_to_state()
                st.rerun()

        if st.button("Скрыть сводку импорта", key="dismiss_import_summary"):
            del st.session_state["last_import_summary"]
            st.rerun()


def _apply_autofixes_to_state() -> None:
    """Применить автофиксы к текущему builder_state.

    Алгоритм:
    1. Собрать docx из текущего state (через _build_document_from_state).
    2. Распарсить docx обратно в Document.
    3. Прогнать fixer.fix() — мутирует Document на месте.
    4. Преобразовать Document обратно в state (document_to_state).
    5. Записать в session_state и пересчитать summary.

    Через docx-touche цикл, потому что fixer работает на модели
    Document, а builder-state хранит данные в собственном dict-формате.
    Альтернативой был бы прямой fixer-over-state, но это удвоит код
    fixer-а — не нужно.
    """
    from gostforge.fixer.engine import fix as run_fix  # noqa: PLC0415
    from gostforge.parser import parse_docx  # noqa: PLC0415

    state = st.session_state.get("builder_state")
    if not state:
        return

    profile_id = state.get("profile_id", "gost-7.32-2017")

    try:
        data = _build_document_from_state(state)
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        document = parse_docx(tmp_path)
        profile = load_profile(profile_id)
        applied = run_fix(document, profile)
        new_state = document_to_state(document)
    except Exception as exc:  # noqa: BLE001 - UI feedback
        st.error(f"Не удалось применить автофиксы: {exc}")
        return

    if not applied:
        st.info("Автофиксы не нашли исправимых нарушений.")
        return

    _normalize_state_paragraphs(new_state)
    st.session_state["builder_state"] = new_state

    # Пересчитываем summary поверх нового state.
    summary_new = _compute_import_violations_summary(document, profile_id)
    last = st.session_state.get("last_import_summary", {})
    last.update(summary_new)
    last["applied_fixes"] = len(applied)
    st.session_state["last_import_summary"] = last
    st.success(f"Применено автофиксов: {len(applied)}. Сводка обновлена.")


def _move_section_to(from_idx: int, to_idx: int) -> None:
    """Переместить раздел из позиции from_idx в позицию to_idx.

    Корректно обновляет active_section_index: если активная секция —
    та, что перемещается, её индекс «следует» за ней.
    """
    state = _get_state()
    sections = state["sections"]
    if from_idx < 0 or from_idx >= len(sections):
        return
    to_idx = max(0, min(to_idx, len(sections) - 1))
    if from_idx == to_idx:
        return
    item = sections.pop(from_idx)
    sections.insert(to_idx, item)

    active = state.get("active_section_index", 0)
    if active == from_idx:
        state["active_section_index"] = to_idx
    elif from_idx < to_idx and from_idx < active <= to_idx:
        # Раздел сдвинулся вниз — все между ним и новой позицией поднялись на 1.
        state["active_section_index"] = active - 1
    elif to_idx <= active < from_idx:
        # Раздел сдвинулся вверх — все между ним и новой позицией опустились на 1.
        state["active_section_index"] = active + 1


def _duplicate_section(idx: int) -> None:
    """Дублировать раздел по индексу: вставить копию сразу после оригинала.

    Полезно при создании однотипных глав («Глава 1», «Глава 2», ...).
    К заголовку дубликата добавляется " (копия)" чтобы пользователь
    сразу увидел, какой раздел свежесозданный.

    Глубокая копия через json round-trip: state — это nested dict/list
    из примитивов, поэтому json.loads(json.dumps(...)) корректно
    воспроизводит структуру и заодно отвязывает изменения копии от
    оригинала.
    """
    state = _get_state()
    sections = state["sections"]
    if idx < 0 or idx >= len(sections):
        return
    original = sections[idx]
    copy = json.loads(json.dumps(original))
    original_heading = str(copy.get("heading", "Раздел")).strip()
    copy["heading"] = f"{original_heading} (копия)"
    # Bib-секцию НЕ дублируем как is_bibliography — две bib-секции
    # запутают валидатор и UI. Превратим копию в обычный раздел.
    if copy.get("is_bibliography"):
        copy["is_bibliography"] = False
        copy.pop("references", None)
    sections.insert(idx + 1, copy)
    state["active_section_index"] = idx + 1


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


# Группировка кодов проверок по категориям для UI multi-select.
# Источник: gostforge.validator.engine.registered_checks() — но мы хотим
# фиксированный человекочитаемый порядок и подписи. Если в реестре
# появится новая категория — её надо добавить сюда.
_CHECK_CATEGORIES: dict[str, str] = {
    "F.": "Поля и страница",
    "T.": "Типографика",
    "H.": "Заголовки",
    "S.": "Структура",
    "R.": "Источники",
    "B.": "Библиография",
    "I.": "Рисунки/таблицы",
    "L.": "Списки",
    "C.": "Перекрёстные ссылки",
    "M.": "Формулы",
    "A.": "Сокращения",
    "K.": "Колонтитулы",
    "V.": "Объём",
    "P.": "Приложения",
    "X.": "Прочее",
}


def _list_available_check_codes() -> list[str]:
    """Все зарегистрированные коды проверок (для multi-select)."""
    from gostforge.validator.engine import registered_checks  # noqa: PLC0415

    return registered_checks()


def _render_section_validation_panel(
    section: dict[str, Any], idx: int
) -> None:
    """Панель «Нормоконтроль раздела» — отключение проверок для конкретного раздела.

    Студент может пометить раздел (титульный, реферат, приложения) как
    «не подчиняющийся правилам ГОСТа» — указав конкретные коды проверок
    или отключив все. UI хранит выбор в ``section["disabled_checks"]``
    как list[str]. ``["*"]`` = отключить все.
    """
    section.setdefault("disabled_checks", [])
    disabled: list[str] = list(section["disabled_checks"])
    skip_all = "*" in disabled
    selected_codes = [c for c in disabled if c != "*"]

    with st.expander("Нормоконтроль раздела", expanded=False):
        st.caption(
            "Отключите проверки, которые не должны применяться к этому "
            "разделу. Это нужно для титульного листа, реферата и приложений: "
            "они оформляются по своим правилам и не по ГОСТу."
        )

        new_skip_all = st.checkbox(
            "Не проверять этот раздел нормоконтролем",
            value=skip_all,
            key=f"sec_skip_all_{idx}",
            help=(
                "Все нарушения с location-ом, указывающим на этот раздел, "
                "будут отфильтрованы. Глобальные нарушения "
                "(структура документа, объём) останутся."
            ),
        )

        if new_skip_all:
            section["disabled_checks"] = ["*"]
            st.info(
                "Все проверки этого раздела отключены. "
                "Снимите галочку выше, чтобы выбрать отдельные коды."
            )
            return

        all_codes = _list_available_check_codes()
        # Группируем по категориям для UX.
        groups: dict[str, list[str]] = {}
        for code in all_codes:
            prefix = code[:2]  # "F.", "T.", ...
            groups.setdefault(prefix, []).append(code)

        st.caption(
            "Или выберите конкретные проверки для отключения:"
        )
        new_selected: list[str] = []
        for prefix, codes in groups.items():
            label = _CHECK_CATEGORIES.get(prefix, prefix)
            # Преселект текущих выбранных кодов из этой категории.
            preselected = [c for c in codes if c in selected_codes]
            picked = st.multiselect(
                label,
                options=codes,
                default=preselected,
                key=f"sec_disabled_{idx}_{prefix.strip('.')}",
            )
            new_selected.extend(picked)

        section["disabled_checks"] = sorted(new_selected)

        if new_selected:
            st.success(
                f"Отключено проверок: {len(new_selected)} "
                f"({', '.join(new_selected[:5])}"
                f"{'…' if len(new_selected) > 5 else ''})"
            )


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

    # Быстрое переупорядочивание: select-box с целевой позицией.
    # Альтернатива drag-and-drop, не требующая внешних библиотек.
    if len(sections) > 1:
        with st.expander("Переместить раздел", expanded=False):
            target = st.selectbox(
                "Новая позиция",
                options=list(range(1, len(sections) + 1)),
                index=idx,
                format_func=lambda n: f"Позиция {n}",
                key=f"move_section_target_{idx}",
            )
            if st.button(
                "Переместить",
                key=f"move_section_btn_{idx}",
                disabled=(target - 1) == idx,
            ):
                _move_section_to(idx, target - 1)
                st.rerun()

    _render_section_validation_panel(section, idx)

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


def _render_paragraph_inline_editor(block: dict[str, Any], *, base: str) -> None:
    """Inline-редактор параграфа: список run-ов + панель добавления (Фаза 2.5).

    Каждый run отображается отдельной строкой со своим редактором —
    text_area + чекбоксы B/I/U для TextRun, select + поля для xref /
    formula / citation. Поддерживаются перемещение run-а вверх/вниз
    и удаление.

    Внизу — четыре кнопки добавления: + Текст, + Формула, + Ссылка,
    + Цитата. Каждая добавляет stub-run и триггерит rerun.
    """
    # Гарантируем что block в формате runs (нормализация на месте).
    _normalize_paragraph_state(block)
    runs: list[dict[str, Any]] = block.setdefault("runs", [])
    state = _get_state()

    if not runs:
        st.caption("Параграф пуст — добавьте элементы кнопками ниже.")

    for r_idx in list(range(len(runs))):
        if r_idx >= len(runs):
            break
        _render_inline_run_row(
            runs[r_idx],
            runs,
            r_idx,
            base=f"{base}_r{r_idx}",
            state=state,
        )

    # --- Панель добавления нового run-а ---
    cols = st.columns(4)
    if cols[0].button("+ Текст", key=f"{base}_addtext"):
        runs.append({"kind": "text", "text": ""})
        st.rerun()
    if cols[1].button("+ Формула", key=f"{base}_addformula"):
        runs.append({"kind": "formula", "latex": ""})
        st.rerun()
    if cols[2].button("+ Ссылка", key=f"{base}_addxref"):
        targets = _collect_xref_targets(state)
        target_id = targets[0][0] if targets else ""
        runs.append({"kind": "xref", "target_id": target_id, "prefix": ""})
        st.rerun()
    if cols[3].button("+ Цитата", key=f"{base}_addcitation"):
        options = _collect_bibliography_options(state)
        source = options[0][0] if options else ""
        runs.append({"kind": "citation", "source_id": source})
        st.rerun()


def _render_inline_run_row(
    run: dict[str, Any],
    runs: list[dict[str, Any]],
    r_idx: int,
    *,
    base: str,
    state: dict[str, Any],
) -> None:
    """Одна строка inline-редактора: редактор run-а + кнопки управления."""
    kind = run.get("kind", "text")
    with st.container():
        if kind == "text":
            _render_text_run_editor(run, base=base)
        elif kind == "formula":
            _render_inline_formula_editor(run, base=base)
        elif kind == "xref":
            _render_xref_editor(run, base=base, state=state)
        elif kind == "citation":
            _render_citation_editor(run, base=base, state=state)
        else:
            st.warning(f"Неизвестный inline-элемент: {kind}")

        # Кнопки управления: ↑ ↓ ×.
        b_cols = st.columns([1, 1, 1, 12])
        if r_idx > 0 and b_cols[0].button("↑", key=f"{base}_up", help="Переместить выше"):
            runs[r_idx - 1], runs[r_idx] = runs[r_idx], runs[r_idx - 1]
            st.rerun()
        if r_idx < len(runs) - 1 and b_cols[1].button(
            "↓", key=f"{base}_down", help="Переместить ниже"
        ):
            runs[r_idx + 1], runs[r_idx] = runs[r_idx], runs[r_idx + 1]
            st.rerun()
        if b_cols[2].button("×", key=f"{base}_del", help="Удалить элемент"):
            runs.pop(r_idx)
            st.rerun()


def _render_text_run_editor(run: dict[str, Any], *, base: str) -> None:
    """Редактор одного TextRun: text + B/I/U/sup/sub."""
    run["text"] = st.text_area(
        "Фрагмент текста",
        value=str(run.get("text", "")),
        key=f"{base}_text",
        height=80,
        label_visibility="collapsed",
    )
    cols = st.columns(5)
    run["bold"] = cols[0].checkbox(
        "B", value=bool(run.get("bold")), key=f"{base}_bold", help="Полужирный"
    )
    run["italic"] = cols[1].checkbox(
        "I", value=bool(run.get("italic")), key=f"{base}_italic", help="Курсив"
    )
    run["underline"] = cols[2].checkbox(
        "U", value=bool(run.get("underline")), key=f"{base}_underline", help="Подчёркивание"
    )
    run["superscript"] = cols[3].checkbox(
        "x²", value=bool(run.get("superscript")), key=f"{base}_sup", help="Верхний индекс"
    )
    run["subscript"] = cols[4].checkbox(
        "x₂", value=bool(run.get("subscript")), key=f"{base}_sub", help="Нижний индекс"
    )
    # False сериализуется в state как явное «не задано» — чистим, чтобы
    # JSON-save не разбухал лишними false-полями.
    for attr in ("bold", "italic", "underline", "superscript", "subscript"):
        if run.get(attr) is False:
            run.pop(attr, None)


def _render_inline_formula_editor(run: dict[str, Any], *, base: str) -> None:
    """Редактор inline-формулы: LaTeX-input + live preview через st.latex."""
    st.markdown("**∫ Формула** (inline)")
    run["latex"] = st.text_input(
        "LaTeX",
        value=str(run.get("latex", "")),
        key=f"{base}_latex",
        label_visibility="collapsed",
    )
    if run["latex"]:
        try:
            st.latex(run["latex"])
        except Exception as exc:  # pragma: no cover — UI fallback
            st.caption(f"Не удалось отрендерить превью: {exc}")


def _render_xref_editor(run: dict[str, Any], *, base: str, state: dict[str, Any]) -> None:
    """Редактор перекрёстной ссылки: select target + текст prefix."""
    st.markdown("**→ Перекрёстная ссылка**")
    targets = _collect_xref_targets(state)
    if not targets:
        st.warning(
            "В работе пока нет рисунков, таблиц или нумерованных формул. "
            "Добавьте их в разделах, потом возвращайтесь к ссылке."
        )
        run["target_id"] = st.text_input(
            "ID цели (вручную)",
            value=str(run.get("target_id", "")),
            key=f"{base}_tgt",
        )
    else:
        values = [t[0] for t in targets]
        labels = [t[1] for t in targets]
        current = str(run.get("target_id") or "")
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        sel = st.selectbox(
            "Цель",
            options=list(range(len(values))),
            index=idx,
            format_func=lambda i: labels[i],
            key=f"{base}_tgtsel",
        )
        run["target_id"] = values[sel]
    run["prefix"] = st.text_input(
        "Префикс (например, « (см. »)",
        value=str(run.get("prefix") or ""),
        key=f"{base}_prefix",
    )
    if not run.get("prefix"):
        run.pop("prefix", None)


def _render_citation_editor(run: dict[str, Any], *, base: str, state: dict[str, Any]) -> None:
    """Редактор библиографической цитаты: select bib-N + опц. pages."""
    st.markdown("**[ ] Цитата на источник**")
    options = _collect_bibliography_options(state)
    if not options:
        st.warning(
            "В разделе «Список использованных источников» пока нет записей. "
            "Добавьте их, потом возвращайтесь к цитате."
        )
        run["source_id"] = st.text_input(
            "ID источника (вручную)",
            value=str(run.get("source_id", "")),
            key=f"{base}_src",
        )
    else:
        values = [o[0] for o in options]
        labels = [o[1] for o in options]
        current = str(run.get("source_id") or "")
        try:
            idx = values.index(current)
        except ValueError:
            idx = 0
        sel = st.selectbox(
            "Источник",
            options=list(range(len(values))),
            index=idx,
            format_func=lambda i: labels[i],
            key=f"{base}_srcsel",
        )
        run["source_id"] = values[sel]
    pages = st.text_input(
        "Страницы (например, «12-15»)",
        value=str(run.get("pages") or ""),
        key=f"{base}_pages",
    )
    if pages:
        run["pages"] = pages
        run["template"] = "[{n}, с. {pages}]"
    else:
        run.pop("pages", None)
        run.pop("template", None)


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
        _render_paragraph_inline_editor(block, base=base)
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
    """Список подразделов раздела с собственными блоками.

    Поддерживается 2 уровня вложенности: subsection (level=2) и
    sub-subsection (level=3). Глубже builder тоже работает, но UI
    становится визуально перегруженным, поэтому ограничен.
    """
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

            # Подразделы 3-го уровня (sub-subsections).
            _render_subsubsections_editor(sub, sec_idx, s_idx)

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
                "subsections": [],
            }
        )
        st.rerun()


def _render_subsubsections_editor(
    sub: dict[str, Any], sec_idx: int, s_idx: int
) -> None:
    """Список пунктов 3-го уровня (например 1.1.1, 1.1.2)."""
    subsubs = sub.setdefault("subsections", [])
    st.markdown("**Пункты**")
    if not subsubs:
        st.caption("Пунктов нет.")
    for ss_idx, subsub in enumerate(subsubs):
        with st.expander(
            f"{sec_idx + 1}.{s_idx + 1}.{ss_idx + 1} "
            f"{subsub.get('heading') or '(без названия)'}",
            expanded=False,
        ):
            subsub["heading"] = st.text_input(
                "Название пункта",
                value=subsub.get("heading", ""),
                key=f"subsub_heading_{sec_idx}_{s_idx}_{ss_idx}",
            )
            subsub_blocks = subsub.setdefault("blocks", [])
            prefix = f"sec{sec_idx}_sub{s_idx}_ss{ss_idx}"
            _render_blocks_editor(subsub_blocks, key_prefix=prefix)
            _render_add_block_buttons(subsub_blocks, key_prefix=prefix)
            if st.button(
                "Удалить пункт",
                key=f"del_subsub_{sec_idx}_{s_idx}_{ss_idx}",
            ):
                subsubs.pop(ss_idx)
                st.rerun()

    if st.button(
        "+ Пункт",
        key=f"add_subsub_{sec_idx}_{s_idx}",
    ):
        subsubs.append(
            {
                "id": f"subsub-{sec_idx}-{s_idx}-{len(subsubs) + 1}",
                "heading": f"Пункт {len(subsubs) + 1}",
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
    """Кнопка генерации .docx + live-preview нарушений + превью PDF."""
    state = _get_state()
    st.divider()
    st.subheader("Генерация документа")
    if not (state.get("title") or "").strip():
        st.warning("Укажите название работы в sidebar — иначе документ не собрать.")
        return
    cols = st.columns(2)
    do_generate = cols[0].button("Сгенерировать .docx", key="builder_generate")
    do_preview = cols[1].button(
        "Сгенерировать + превью PDF",
        key="builder_generate_preview",
        help="Требует LibreOffice. Превращает .docx → .pdf для просмотра в браузере.",
    )

    if not (do_generate or do_preview):
        return

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
        v_cols = st.columns(3)
        v_cols[0].metric("Ошибок", counts.get("error", 0))
        v_cols[1].metric("Предупр.", counts.get("warning", 0))
        v_cols[2].metric("Инфо", counts.get("info", 0))

    if do_preview:
        _render_pdf_preview(data)


def _render_pdf_preview(docx_data: bytes) -> None:
    """Конвертировать docx → pdf и показать в Streamlit-iframe.

    Требует LibreOffice (см. gostforge.pdf_exporter). При его
    отсутствии — st.error без падения UI.
    """
    from gostforge.pdf_exporter import (  # noqa: PLC0415
        LibreOfficeNotFoundError,
        convert_to_pdf,
    )

    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(docx_data)
            docx_path = Path(tmp.name)
        pdf_path = docx_path.with_suffix(".pdf")
        convert_to_pdf(docx_path, pdf_path)
        pdf_bytes = pdf_path.read_bytes()
    except LibreOfficeNotFoundError:
        st.error(
            "LibreOffice не найден. Установите его, чтобы видеть PDF-превью "
            "(на Windows — https://www.libreoffice.org/download/)."
        )
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось сгенерировать PDF: {exc}")
        return

    st.markdown("**Превью PDF:**")
    # Кнопка скачивания PDF.
    st.download_button(
        "Скачать .pdf",
        data=pdf_bytes,
        file_name="work.pdf",
        mime="application/pdf",
        key="builder_download_pdf",
    )
    # Inline-просмотр через iframe + base64 data URL.
    import base64  # noqa: PLC0415

    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    st.components.v1.html(
        f"""
        <iframe
            src="data:application/pdf;base64,{b64}"
            width="100%"
            height="800px"
            style="border: 1px solid #ddd; border-radius: 4px;">
        </iframe>
        """,
        height=820,
    )


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
    # Phase 2.5: фиксируем snapshot до рендера sidebar, чтобы кнопки
    # undo/redo там же опирались на актуальный cursor.
    _auto_snapshot_if_changed()
    # Авто-сохранение на диск не чаще 1 раза в 30 секунд.
    _autosave_now()
    _render_sidebar_metadata()
    _render_section_templates_sidebar()
    _render_bulk_operations_sidebar()
    _render_autosave_banner()

    st.title("gostforge — конструктор работ")
    st.caption(
        "Соберите работу по ГОСТу из блоков: разделы, подразделы, "
        "параграфы, таблицы, рисунки, списки, формулы и список источников."
    )

    _render_import_violations_panel()
    _render_imported_comments_panel()
    _render_progress_panel()
    _render_section_tree()
    _render_active_section_editor()
    _render_generate_button()


__all__ = ["render_interactive_builder"]
