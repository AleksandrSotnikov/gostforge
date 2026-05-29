"""Редактор профиля форматирования для Streamlit.

Отдельный режим UI: загрузить любой профиль как основу, отредактировать
ВСЕ параметры оформления (поля страницы, основной текст, заголовки 1–4,
подписи, таблицы, рисунки, списки), при желании — состав и важность
проверок, и сохранить результат как пользовательский профиль в локальный
реестр (БД). После сохранения профиль доступен в выпадающем списке
нормоконтроля и конструктора.

Логика преобразования/валидации/сохранения вынесена в чистые функции
(``build_profile_yaml``, ``save_profile_to_registry``) — они тестируются
без Streamlit.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import yaml

from gostforge.profile import list_profiles, load_profile
from gostforge.profile.schema import Profile

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - проверяется при отсутствии пакета
    raise ImportError("Для UI нужен streamlit: pip install 'gostforge[ui]'") from exc

# Наборы допустимых значений (совпадают с Literal-типами схемы).
_ALIGN_FULL = ["left", "right", "center", "justify"]
_ALIGN_FIG = ["left", "center", "right"]
_NUMBERING_MODES = ["continuous", "by_chapter"]
_NUMBERING_LABELS = {
    "continuous": "Сквозная (1, 2, 3, ...)",
    "by_chapter": "По главам (1.1, 1.2, 2.1, ...)",
}
_BORDER = ["single", "double", "dashed", "dotted", "none"]
# Стили линии рамки листа (без "none" — выключение рамки делается чекбоксом).
_BORDER_LINE = ["single", "double", "thick", "dashed", "dotted"]
_OFFSET_FROM = ["text", "page"]
_POSITION = ["above", "below"]
_SEVERITY_DISPLAY = ["(по профилю)", "error", "warning", "info"]

_SESSION_KEY = "profile_editor_data"
_SESSION_BASE = "profile_editor_base"


# --- Чистые helper-функции (тестируются без Streamlit) ----------------------


def profile_to_data(profile: Profile) -> dict[str, Any]:
    """Профиль → редактируемый dict (полный, со всеми полями)."""
    return profile.model_dump()


def build_profile_yaml(data: dict[str, Any]) -> str:
    """Валидировать data через Pydantic и вернуть YAML-текст профиля.

    Бросает ``ValueError`` с понятным сообщением, если данные не проходят
    схему (например, отрицательный кегль или неизвестное выравнивание).
    """
    try:
        profile = Profile(**data)
    except Exception as exc:
        raise ValueError(f"Профиль не прошёл валидацию: {exc}") from exc
    return yaml.safe_dump(
        profile.model_dump(),
        allow_unicode=True,
        sort_keys=False,
    )


_UNCHANGED = object()


def _diff(base: Any, edited: Any) -> Any:
    """Вернуть часть ``edited``, отличающуюся от ``base``.

    Для совпадающих значений возвращает сентинел ``_UNCHANGED``. dict
    обходится рекурсивно (только изменённые ключи), list и скаляры
    берутся целиком при любом отличии — это согласовано с правилами
    ``_deep_merge`` при наследовании профилей.
    """
    if isinstance(base, dict) and isinstance(edited, dict):
        out: dict[str, Any] = {}
        for key, edited_value in edited.items():
            if key not in base:
                out[key] = edited_value
                continue
            sub = _diff(base[key], edited_value)
            if sub is not _UNCHANGED:
                out[key] = sub
        return out if out else _UNCHANGED
    return _UNCHANGED if base == edited else edited


def _flatten_changes(base: Any, edited: Any, prefix: str = "") -> list[str]:
    """Плоский список изменений ``edited`` относительно ``base``.

    Возвращает строки вида ``путь: было → стало`` для скаляров и
    ``путь: изменён список`` для списков. Для вложенных dict рекурсия.
    """
    changes: list[str] = []
    if isinstance(base, dict) and isinstance(edited, dict):
        for key, edited_value in edited.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in base:
                changes.append(f"{path}: добавлено → {edited_value!r}")
            else:
                changes.extend(_flatten_changes(base[key], edited_value, path))
        return changes
    if isinstance(base, list) and isinstance(edited, list):
        if base != edited:
            changes.append(f"{prefix}: изменён список")
        return changes
    if base != edited:
        changes.append(f"{prefix}: {base!r} → {edited!r}")
    return changes


def build_extends_profile_yaml(data: dict[str, Any], base_id: str) -> str:
    """YAML профиля-наследника: ``extends: base_id`` + только отличия.

    В отличие от :func:`build_profile_yaml` (полный снимок), сохраняется
    минимальный diff поверх базового профиля — при обновлении базового
    стандарта наследник подхватит изменения неизменённых параметров.
    """
    base = load_profile(base_id).model_dump()
    result: dict[str, Any] = {
        "id": (data.get("id") or "").strip(),
        "name": data.get("name", ""),
        "version": data.get("version", "1.0"),
        "extends": base_id,
    }
    if data.get("description"):
        result["description"] = data["description"]
    for key in ("styles", "checks", "sections_template"):
        sub = _diff(base.get(key), data.get(key))
        if sub is not _UNCHANGED and sub:
            result[key] = sub

    # Структурная валидация (типы значений в diff'е); сам diff и пишем.
    try:
        Profile(**result)
    except Exception as exc:
        raise ValueError(f"Профиль не прошёл валидацию: {exc}") from exc
    return yaml.safe_dump(result, allow_unicode=True, sort_keys=False)


def save_profile_to_registry(yaml_content: str, *, overwrite: bool) -> str:
    """Установить YAML-профиль в локальный реестр (БД). Возвращает id.

    Тонкая обёртка над ``gostforge.db.install_profile`` — здесь, чтобы
    UI не знал про детали БД, а тесты могли проверить путь сохранения.
    """
    from gostforge.db import get_connection, install_profile

    with get_connection() as conn:
        record = install_profile(
            conn, yaml_content=yaml_content, source="profile-editor", overwrite=overwrite
        )
    return record.profile_id


def list_installed_custom_profiles() -> list[dict[str, str]]:
    """Список установленных пользовательских профилей из реестра (БД).

    Возвращает [] при недоступной БД — чтобы UI не падал.
    """
    try:
        from gostforge.db import get_connection, list_custom_profiles
    except ImportError:
        return []
    try:
        with get_connection() as conn:
            records = list_custom_profiles(conn)
    except Exception:
        return []
    return [
        {
            "id": r.profile_id,
            "name": r.name,
            "version": r.version,
            "source": r.source,
            "installed_at": r.installed_at,
        }
        for r in records
    ]


def delete_custom_profile(profile_id: str) -> bool:
    """Удалить пользовательский профиль из реестра. True если был удалён."""
    from gostforge.db import get_connection, uninstall_profile

    with get_connection() as conn:
        return uninstall_profile(conn, profile_id)


# --- Streamlit-виджеты для групп параметров ---------------------------------


def _num(
    label: str, value: Any, key: str, *, step: float = 0.5, min_value: float | None = 0.0
) -> float:
    return float(
        st.number_input(label, value=float(value), step=step, min_value=min_value, key=key)
    )


def _select(
    label: str,
    options: list[str],
    value: str,
    key: str,
    *,
    format_func: Callable[[str], str] | None = None,
) -> str:
    idx = options.index(value) if value in options else 0
    kwargs: dict[str, Any] = {"options": options, "index": idx, "key": key}
    if format_func is not None:
        kwargs["format_func"] = format_func
    return str(st.selectbox(label, **kwargs))


def _edit_metadata(data: dict[str, Any]) -> None:
    st.subheader("Метаданные профиля")
    c1, c2, c3 = st.columns(3)
    data["id"] = c1.text_input("ID (латиницей)", value=data.get("id", ""), key="pe_id").strip()
    data["name"] = c2.text_input("Название", value=data.get("name", ""), key="pe_name")
    data["version"] = c3.text_input("Версия", value=data.get("version", "1.0"), key="pe_version")
    data["description"] = st.text_area(
        "Описание", value=data.get("description", ""), key="pe_descr", height=68
    )


def _edit_page(data: dict[str, Any]) -> None:
    page = data["styles"]["page"]
    page["size"] = st.text_input("Размер листа", value=page.get("size", "A4"), key="pe_page_size")
    st.caption("Поля страницы, мм")
    m = page["margins_mm"]
    cols = st.columns(4)
    m["top"] = _num("Верхнее", m.get("top", 20), "pe_m_top")
    m["right"] = _num("Правое", m.get("right", 15), "pe_m_right")
    m["bottom"] = _num("Нижнее", m.get("bottom", 20), "pe_m_bottom")
    m["left"] = _num("Левое", m.get("left", 30), "pe_m_left")
    # Прокидываем значения в нужные колонки (number_input уже отрисован выше
    # последовательно — Streamlit разложит по колонкам через with-контекст).
    del cols  # колонки не используем для layout, оставляем вертикально

    _edit_page_border(page)


def _edit_page_border(page: dict[str, Any]) -> None:
    """Рамка листа (ЕСКД, ГОСТ 2.104) — раздел редактора профиля «Страница».

    Рамка опциональна и различается у специальностей: чекбокс включает её
    и раскрывает параметры, снятие чекбокса записывает ``border = None``.
    """
    st.caption("Рамка листа (ЕСКД, ГОСТ 2.104)")
    border = dict(page.get("border") or {})
    enabled = st.checkbox(
        "Рисовать рамку листа",
        value=bool(border.get("enabled", False)),
        key="pe_page_border_en",
        help=(
            "Для технической/конструкторской документации (ЕСКД). Для рамки "
            "по границе текста задайте поля 20/5/5/5 мм и «Отсчёт отступа: text»."
        ),
    )
    if not enabled:
        page["border"] = None
        return
    border["enabled"] = True
    border["style"] = _select(
        "Стиль линии", _BORDER_LINE, border.get("style", "single"), "pe_page_border_style"
    )
    border["size_eighth_pt"] = int(
        st.number_input(
            "Толщина линии (1/8 pt: 4 = 0.5 pt, 8 = 1 pt)",
            value=int(border.get("size_eighth_pt", 4)),
            min_value=1,
            max_value=96,
            step=1,
            key="pe_page_border_sz",
        )
    )
    border["color"] = st.text_input(
        "Цвет (auto или hex без #)",
        value=str(border.get("color", "auto")),
        key="pe_page_border_color",
    )
    border["offset_from"] = _select(
        "Отсчёт отступа", _OFFSET_FROM, border.get("offset_from", "text"), "pe_page_border_off"
    )
    border["space_pt"] = int(
        st.number_input(
            "Отступ рамки на сторону (pt, 0..31)",
            value=int(border.get("space_pt", 0)),
            min_value=0,
            max_value=31,
            step=1,
            key="pe_page_border_space",
        )
    )
    page["border"] = border


def _edit_body(data: dict[str, Any]) -> None:
    b = data["styles"]["body"]
    b["font"] = st.text_input("Шрифт", value=b["font"], key="pe_body_font")
    b["size_pt"] = _num("Кегль (pt)", b["size_pt"], "pe_body_size", step=0.5, min_value=1.0)
    b["line_spacing"] = _num("Межстрочный интервал", b["line_spacing"], "pe_body_ls", step=0.1)
    b["first_line_indent_cm"] = _num(
        "Абзацный отступ (см)", b["first_line_indent_cm"], "pe_body_ind", step=0.05
    )
    b["alignment"] = _select("Выравнивание", _ALIGN_FULL, b["alignment"], "pe_body_align")
    b["hyphenation"] = st.checkbox("Переносы слов", value=b["hyphenation"], key="pe_body_hyph")
    b["space_before_pt"] = _num("Интервал перед абзацем (pt)", b["space_before_pt"], "pe_body_sb")
    b["space_after_pt"] = _num("Интервал после абзаца (pt)", b["space_after_pt"], "pe_body_sa")


def _edit_heading(h: dict[str, Any], prefix: str) -> None:
    h["font"] = st.text_input("Шрифт", value=h["font"], key=f"{prefix}_font")
    h["size_pt"] = _num("Кегль (pt)", h["size_pt"], f"{prefix}_size", step=0.5, min_value=1.0)
    c1, c2, c3 = st.columns(3)
    with c1:
        h["bold"] = st.checkbox("Полужирный", value=h["bold"], key=f"{prefix}_bold")
    with c2:
        h["italic"] = st.checkbox("Курсив", value=h["italic"], key=f"{prefix}_italic")
    with c3:
        h["uppercase"] = st.checkbox("ВЕРХНИЙ регистр", value=h["uppercase"], key=f"{prefix}_upper")
    h["color"] = st.text_input("Цвет (auto или hex без #)", value=h["color"], key=f"{prefix}_color")
    h["alignment"] = _select("Выравнивание", _ALIGN_FULL, h["alignment"], f"{prefix}_align")
    h["first_line_indent_cm"] = _num(
        "Абзацный отступ (см)", h["first_line_indent_cm"], f"{prefix}_ind", step=0.05
    )
    h["line_spacing"] = _num("Межстрочный интервал", h["line_spacing"], f"{prefix}_ls", step=0.1)
    h["spacing_before_pt"] = _num("Интервал перед (pt)", h["spacing_before_pt"], f"{prefix}_sb")
    h["spacing_after_pt"] = _num("Интервал после (pt)", h["spacing_after_pt"], f"{prefix}_sa")
    c4, c5 = st.columns(2)
    with c4:
        h["page_break_before"] = st.checkbox(
            "С новой страницы", value=h["page_break_before"], key=f"{prefix}_pbb"
        )
    with c5:
        h["keep_with_next"] = st.checkbox(
            "Не отрывать от текста", value=h["keep_with_next"], key=f"{prefix}_kwn"
        )


def _edit_caption(cap: dict[str, Any], prefix: str) -> None:
    cap["font"] = st.text_input("Шрифт подписи", value=cap["font"], key=f"{prefix}_font")
    cap["size_pt"] = _num("Кегль (pt)", cap["size_pt"], f"{prefix}_size", step=0.5, min_value=1.0)
    c1, c2 = st.columns(2)
    with c1:
        cap["bold"] = st.checkbox("Полужирный", value=cap["bold"], key=f"{prefix}_bold")
    with c2:
        cap["italic"] = st.checkbox("Курсив", value=cap["italic"], key=f"{prefix}_italic")
    cap["alignment"] = _select("Выравнивание", _ALIGN_FULL, cap["alignment"], f"{prefix}_align")
    cap["position"] = _select("Положение", _POSITION, cap["position"], f"{prefix}_pos")
    cap["format"] = st.text_input(
        "Шаблон ({num}, {title})", value=cap["format"], key=f"{prefix}_fmt"
    )
    cap["spacing_before_pt"] = _num("Интервал перед (pt)", cap["spacing_before_pt"], f"{prefix}_sb")
    cap["spacing_after_pt"] = _num("Интервал после (pt)", cap["spacing_after_pt"], f"{prefix}_sa")
    c3, c4 = st.columns(2)
    with c3:
        cap["keep_together"] = st.checkbox(
            "Не разрывать подпись", value=cap["keep_together"], key=f"{prefix}_kt"
        )
    with c4:
        cap["keep_with_next"] = st.checkbox(
            "Не отрывать от объекта", value=cap["keep_with_next"], key=f"{prefix}_kwn"
        )


def _edit_table(data: dict[str, Any]) -> None:
    t = data["styles"]["table"]
    t["border_style"] = _select("Стиль рамок", _BORDER, t["border_style"], "pe_tb_border")
    t["border_size"] = int(
        st.number_input(
            "Толщина рамки (1/8 pt)",
            value=int(t["border_size"]),
            min_value=0,
            step=1,
            key="pe_tb_bsize",
        )
    )
    t["border_color"] = st.text_input(
        "Цвет рамки (auto/hex)", value=t["border_color"], key="pe_tb_bcolor"
    )
    # cell_font / cell_size_pt — Optional. Пустое поле / снятый чекбокс = None
    # (= наследовать от основного текста).
    cf = st.text_input(
        "Шрифт ячеек (пусто = как у текста)", value=t.get("cell_font") or "", key="pe_tb_cfont"
    ).strip()
    t["cell_font"] = cf or None
    use_cell_size = st.checkbox(
        "Задать кегль ячеек", value=t.get("cell_size_pt") is not None, key="pe_tb_use_csize"
    )
    if use_cell_size:
        t["cell_size_pt"] = _num(
            "Кегль ячеек (pt)", t.get("cell_size_pt") or 12, "pe_tb_csize", step=0.5, min_value=1.0
        )
    else:
        t["cell_size_pt"] = None
    t["header_bold"] = st.checkbox("Полужирная шапка", value=t["header_bold"], key="pe_tb_hbold")
    t["header_alignment"] = _select(
        "Выравнивание шапки", _ALIGN_FULL, t["header_alignment"], "pe_tb_halign"
    )
    t["numbering"] = _select(
        "Нумерация таблиц",
        _NUMBERING_MODES,
        t.get("numbering", "continuous"),
        "pe_tb_num",
        format_func=lambda v: _NUMBERING_LABELS.get(v, v),
    )
    t["repeat_header"] = st.checkbox(
        "Повторять шапку при переносе на новую страницу",
        value=t.get("repeat_header", True),
        key="pe_tb_repeat_h",
        help="ГОСТ 7.32: шапка таблицы должна повторяться на каждой continuation-странице.",
    )
    t["continuation_caption"] = st.checkbox(
        "Добавлять строку «Продолжение таблицы N»",
        value=t.get("continuation_caption", False),
        key="pe_tb_cont_cap",
        help=(
            "Word покажет строку и на первой странице, и на continuation. "
            "Чисто-OOXML способа показывать её только на 2+ странице нет."
        ),
    )
    t["cell_alignment"] = _select(
        "Выравнивание ячеек", _ALIGN_FULL, t["cell_alignment"], "pe_tb_calign"
    )
    t["cell_first_line_indent_cm"] = _num(
        "Абзацный отступ в ячейках (см)", t["cell_first_line_indent_cm"], "pe_tb_cind", step=0.05
    )
    t["cell_line_spacing"] = _num(
        "Межстрочный в ячейках", t["cell_line_spacing"], "pe_tb_cls", step=0.1
    )
    t["cell_space_before_pt"] = _num("Интервал перед (pt)", t["cell_space_before_pt"], "pe_tb_csb")
    t["cell_space_after_pt"] = _num("Интервал после (pt)", t["cell_space_after_pt"], "pe_tb_csa")
    st.markdown("**Подпись таблицы**")
    _edit_caption(t["caption"], "pe_tbcap")


def _edit_figure(data: dict[str, Any]) -> None:
    f = data["styles"]["figure"]
    f["alignment"] = _select("Выравнивание рисунка", _ALIGN_FIG, f["alignment"], "pe_fig_align")
    f["max_width_cm"] = _num(
        "Макс. ширина (см)", f["max_width_cm"], "pe_fig_mw", step=0.5, min_value=1.0
    )
    f["max_height_cm"] = _num(
        "Макс. высота (см)",
        f.get("max_height_cm", 22.0),
        "pe_fig_mh",
        step=0.5,
        min_value=1.0,
    )
    # Схема нумерации: «Рисунок 1» (сквозная) или «Рисунок 3.1» (по главам).
    # В приложениях нумерация всегда буквенная независимо от выбора.
    f["numbering"] = _select(
        "Нумерация рисунков",
        _NUMBERING_MODES,
        f.get("numbering", "continuous"),
        "pe_fig_num",
        format_func=lambda v: _NUMBERING_LABELS.get(v, v),
    )
    f["keep_with_next"] = st.checkbox(
        "Не отрывать рисунок от подписи", value=f["keep_with_next"], key="pe_fig_kwn"
    )
    st.markdown("**Подпись рисунка**")
    _edit_caption(f["caption"], "pe_figcap")


# Соответствие отображаемого названия символа после номера ↔ internal-значению
# (поле «Символ после номера» диалога Word «Изменение отступов в списке»).
_LIST_SUFFIX_DISPLAY = {"Знак табуляции": "tab", "Пробел": "space", "Нет": "nothing"}


def _edit_lists(data: dict[str, Any]) -> None:
    li = data["styles"]["lists"]
    li["bullet_char"] = st.text_input(
        "Символ маркера", value=li["bullet_char"], key="pe_list_bullet"
    )
    li["ordered_format"] = st.text_input(
        "Шаблон нумерации ({n})", value=li["ordered_format"], key="pe_list_fmt"
    )
    # Поля в терминах диалога Word «Изменение отступов в списке».
    # «Отступ текста» = left_indent_cm; «Положение маркера» =
    # left_indent_cm − hanging_indent_cm.
    text_indent = _num(
        "Отступ текста (см)", li["left_indent_cm"], "pe_list_text", step=0.05, min_value=0.0
    )
    marker_pos = _num(
        "Положение маркера (см)",
        li["left_indent_cm"] - li["hanging_indent_cm"],
        "pe_list_marker",
        step=0.05,
        min_value=0.0,
    )
    # «Символ после номера» — selectbox по отображаемым названиям с
    # маппингом в internal-значение схемы (tab/space/nothing).
    suffix_options = list(_LIST_SUFFIX_DISPLAY.keys())
    current_internal = li.get("marker_suffix", "tab")
    current_display = next(
        (disp for disp, internal in _LIST_SUFFIX_DISPLAY.items() if internal == current_internal),
        suffix_options[0],
    )
    chosen_display = str(
        st.selectbox(
            "Символ после номера",
            options=suffix_options,
            index=suffix_options.index(current_display),
            key="pe_list_suffix",
        )
    )
    li["left_indent_cm"] = text_indent
    li["hanging_indent_cm"] = text_indent - marker_pos
    li["marker_suffix"] = _LIST_SUFFIX_DISPLAY[chosen_display]
    st.caption(
        "Параметры соответствуют диалогу Word «Изменение отступов в "
        "списке»: «Положение маркера» — где маркер/номер, «Отступ текста» — "
        "где текст и перенос длинной строки, «Символ после номера» — "
        "разделитель между маркером и текстом."
    )


def _edit_checks(data: dict[str, Any]) -> None:
    checks: dict[str, Any] = data.get("checks") or {}
    if not checks:
        st.info("В этом профиле нет настроенных проверок.")
        return
    st.caption(
        "Включение/выключение проверок и их важность. «(по профилю)» — "
        "оставить severity, заданную в самой проверке."
    )
    rows: list[dict[str, Any]] = []
    for code in sorted(checks):
        cfg = checks[code]
        rows.append(
            {
                "Код": code,
                "Включена": bool(cfg.get("enabled", True)),
                "Важность": cfg.get("severity") or _SEVERITY_DISPLAY[0],
            }
        )
    edited = st.data_editor(
        rows,
        key="pe_checks_editor",
        use_container_width=True,
        hide_index=True,
        disabled=["Код"],
        column_config={
            "Важность": st.column_config.SelectboxColumn(
                "Важность", options=_SEVERITY_DISPLAY, required=True
            ),
        },
    )
    for row in edited:
        code = str(row["Код"])
        if code not in checks:
            continue
        checks[code]["enabled"] = bool(row["Включена"])
        sev = row["Важность"]
        checks[code]["severity"] = None if sev == _SEVERITY_DISPLAY[0] else sev


# --- Точка входа режима -----------------------------------------------------


def _render_installed_profiles() -> None:
    """Список установленных пользовательских профилей + удаление."""
    customs = list_installed_custom_profiles()
    label = f"Установленные пользовательские профили ({len(customs)})"
    with st.expander(label, expanded=False):
        if not customs:
            st.caption(
                "Пока нет своих профилей. Отредактируйте параметры ниже и "
                "сохраните — профиль появится здесь и в списках режимов."
            )
            return
        st.table(
            [
                {
                    "ID": c["id"],
                    "Название": c["name"],
                    "Версия": c["version"],
                    "Установлен": c["installed_at"],
                }
                for c in customs
            ]
        )
        to_delete = st.selectbox(
            "Удалить профиль",
            options=[c["id"] for c in customs],
            key="pe_delete_select",
        )
        if st.button("Удалить выбранный профиль", key="pe_delete_btn"):
            if delete_custom_profile(to_delete):
                st.success(f"Профиль «{to_delete}» удалён из реестра.")
                st.rerun()
            else:
                st.warning(f"Профиль «{to_delete}» не найден в реестре.")


def render_profile_editor() -> None:
    """Главный рендер режима «Редактор профиля»."""
    st.title("Редактор профиля форматирования")
    st.caption(
        "Загрузите профиль как основу, измените параметры и сохраните как "
        "свой профиль. Он появится в списке профилей нормоконтроля и конструктора."
    )

    _render_installed_profiles()

    profiles = list_profiles()
    default_base = (
        "gost-7.32-2017" if "gost-7.32-2017" in profiles else (profiles[0] if profiles else "")
    )

    c1, c2 = st.columns([3, 1])
    base_id = c1.selectbox(
        "Базовый профиль",
        options=profiles,
        index=profiles.index(default_base) if default_base in profiles else 0,
        help="Параметры этого профиля загрузятся в редактор как стартовые.",
        key="pe_base_select",
    )
    load_clicked = c2.button("Загрузить параметры", use_container_width=True)

    # Инициализация рабочей копии: при первом заходе или по кнопке «Загрузить».
    if _SESSION_KEY not in st.session_state or load_clicked:
        loaded = profile_to_data(load_profile(base_id))
        # Предлагаем новый id/name, чтобы не перетереть базовый профиль.
        loaded["id"] = f"{base_id}-custom"
        loaded["name"] = f"{loaded.get('name', base_id)} (моя версия)"
        st.session_state[_SESSION_KEY] = loaded
        st.session_state[_SESSION_BASE] = base_id

    data: dict[str, Any] = st.session_state[_SESSION_KEY]

    _edit_metadata(data)

    tabs = st.tabs(
        [
            "Страница",
            "Основной текст",
            "Заголовки",
            "Таблицы",
            "Рисунки",
            "Списки",
            "Проверки",
            "YAML / Сохранить",
        ]
    )
    with tabs[0]:
        _edit_page(data)
    with tabs[1]:
        _edit_body(data)
    with tabs[2]:
        htabs = st.tabs(["Уровень 1", "Уровень 2", "Уровень 3", "Уровень 4"])
        for i, htab in enumerate(htabs, start=1):
            with htab:
                _edit_heading(data["styles"][f"heading_{i}"], f"pe_h{i}")
    with tabs[3]:
        _edit_table(data)
    with tabs[4]:
        _edit_figure(data)
    with tabs[5]:
        _edit_lists(data)
    with tabs[6]:
        _edit_checks(data)
    with tabs[7]:
        _render_yaml_and_save(data, st.session_state.get(_SESSION_BASE, ""))


def _render_yaml_and_save(data: dict[str, Any], base_id: str) -> None:
    mode = st.radio(
        "Способ сохранения",
        options=["Полный снимок", "Наследник базового (extends)"],
        horizontal=True,
        help=(
            "Полный снимок — самодостаточный профиль со всеми параметрами. "
            "Наследник — сохраняются только отличия от базового профиля "
            f"«{base_id}»; при его обновлении наследник подхватит изменения."
        ),
        key="pe_save_mode",
    )
    # Что изменено относительно базового профиля — чтобы пользователь
    # видел свои правки перед сохранением.
    if base_id:
        try:
            base_styles = load_profile(base_id).model_dump()
        except Exception:
            base_styles = {}
        if base_styles:
            changes: list[str] = []
            for key in ("styles", "checks"):
                changes.extend(_flatten_changes(base_styles.get(key), data.get(key), key))
            with st.expander(f"Отличия от базового «{base_id}» ({len(changes)})"):
                if not changes:
                    st.caption("Изменений нет — профиль совпадает с базовым.")
                else:
                    for line in changes:
                        st.markdown(f"- `{line}`")

    try:
        if mode.startswith("Наследник") and base_id:
            yaml_text = build_extends_profile_yaml(data, base_id)
        else:
            yaml_text = build_profile_yaml(data)
    except ValueError as exc:
        st.error(str(exc))
        return

    st.caption("Итоговый YAML профиля (только чтение):")
    st.code(yaml_text, language="yaml")
    st.download_button(
        "Скачать .yaml",
        data=yaml_text.encode("utf-8"),
        file_name=f"{data.get('id', 'profile')}.yaml",
        mime="application/x-yaml",
    )

    st.divider()
    overwrite = st.checkbox(
        "Перезаписать, если профиль с таким ID уже установлен",
        value=False,
        key="pe_overwrite",
    )
    if st.button("Сохранить в реестр профилей", type="primary"):
        pid = (data.get("id") or "").strip()
        if not pid:
            st.error("Укажите ID профиля во вкладке «Метаданные».")
            return
        try:
            saved_id = save_profile_to_registry(yaml_text, overwrite=overwrite)
        except ValueError as exc:
            st.error(f"Не удалось сохранить: {exc}")
            return
        except Exception as exc:
            st.error(f"Ошибка реестра профилей: {exc}")
            return
        st.success(
            f"Профиль «{saved_id}» сохранён. Выберите его в режимах "
            "«Нормоконтроль» / «Конструктор»."
        )
