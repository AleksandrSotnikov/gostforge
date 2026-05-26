"""Pydantic-схема профиля и его загрузка из YAML.

Профиль описывает три аспекта одного стандарта оформления:
1. Стили (для экспортёра)
2. Шаблон секций (для экспортёра)
3. Правила проверок (для валидатора)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class PageGeometryProfile(BaseModel):
    size: str = "A4"
    margins_mm: dict[str, float] = Field(
        default_factory=lambda: {"top": 20, "right": 15, "bottom": 20, "left": 30}
    )


class BodyTextProfile(BaseModel):
    font: str = "Times New Roman"
    size_pt: float = 14
    line_spacing: float = 1.5
    first_line_indent_cm: float = 1.25
    alignment: Literal["left", "right", "center", "justify"] = "justify"
    hyphenation: bool = False


class HeadingStyleProfile(BaseModel):
    """Параметры одного уровня заголовка (применяются экспортёром
    напрямую к стилям Heading1..N документа)."""

    font: str = "Times New Roman"
    size_pt: float = 14
    bold: bool = True
    italic: bool = False
    uppercase: bool = False
    # auto = «использовать default Word» (обычно чёрный). По ГОСТу — auto.
    # Можно указать hex без # ("000000", "FF0000") для явного цвета.
    color: str = "auto"
    alignment: Literal["left", "right", "center", "justify"] = "left"
    first_line_indent_cm: float = 0.0
    line_spacing: float = 1.5
    spacing_before_pt: float = 12
    spacing_after_pt: float = 6
    page_break_before: bool = False
    keep_with_next: bool = True


class CaptionStyleProfile(BaseModel):
    """Параметры стиля подписи (для Caption и подписей рисунков/таблиц)."""

    font: str = "Times New Roman"
    size_pt: float = 12
    italic: bool = False
    bold: bool = False
    alignment: Literal["left", "right", "center", "justify"] = "center"
    spacing_before_pt: float = 6
    spacing_after_pt: float = 6
    # Шаблон форматирования номера и текста подписи.
    # Доступные плейсхолдеры: {num}, {title}.
    format: str = "{num} — {title}"
    position: Literal["above", "below"] = "below"


class TableStyleProfile(BaseModel):
    """Параметры таблиц: рамки, выравнивание, шрифт ячеек."""

    # Стиль рамок: 'single' — обычные линии (по ГОСТу), 'none' — без рамок.
    border_style: Literal["single", "double", "dashed", "dotted", "none"] = "single"
    # Толщина рамки в 1/8 pt — стандартное значение Word. 4 = 0.5pt.
    border_size: int = 4
    # Цвет рамки: 'auto' (чёрный) или hex без #.
    border_color: str = "auto"
    # Шрифт ячеек таблицы. None = использовать body.font.
    cell_font: str | None = None
    # Кегль ячеек. None = использовать body.size_pt.
    cell_size_pt: float | None = None
    # Жирная шапка.
    header_bold: bool = True
    # Выравнивание подписи таблицы.
    caption: CaptionStyleProfile = Field(
        default_factory=lambda: CaptionStyleProfile(
            alignment="left",
            position="above",
            format="Таблица {num} — {title}",
        )
    )


class FigureStyleProfile(BaseModel):
    """Параметры рисунков: выравнивание, подпись."""

    # Выравнивание самого рисунка (центрирование — стандарт).
    alignment: Literal["left", "center", "right"] = "center"
    caption: CaptionStyleProfile = Field(
        default_factory=lambda: CaptionStyleProfile(
            alignment="center",
            position="below",
            format="Рисунок {num} — {title}",
        )
    )


class ListStyleProfile(BaseModel):
    """Параметры маркированных и нумерованных списков."""

    # Символ маркера для bullet-списков (•, –, *, ◦ и т. п.).
    # По ГОСТ Р 7.32-2017 — тире (–). LibreOffice/Word нормально рендерит.
    bullet_char: str = "–"
    # Шаблон нумерации: {n} = номер. Примеры: "{n})", "{n}.", "{n}."
    ordered_format: str = "{n})"
    # Отступ слева для всего списка (см).
    left_indent_cm: float = 1.25
    # Отступ висячего абзаца (для длинных пунктов с переносом).
    hanging_indent_cm: float = 0.5


class StylesProfile(BaseModel):
    page: PageGeometryProfile = Field(default_factory=PageGeometryProfile)
    body: BodyTextProfile = Field(default_factory=BodyTextProfile)
    # Заголовки уровней 1-4. Уровень 1 — главы (введение, главы, заключение).
    # Уровни 2-4 — параграфы / подразделы.
    heading_1: HeadingStyleProfile = Field(
        default_factory=lambda: HeadingStyleProfile(
            uppercase=True,
            alignment="center",
            spacing_before_pt=18,
            spacing_after_pt=12,
            page_break_before=True,
        )
    )
    heading_2: HeadingStyleProfile = Field(
        default_factory=lambda: HeadingStyleProfile(
            uppercase=False,
            alignment="left",
            first_line_indent_cm=1.25,
            spacing_before_pt=12,
            spacing_after_pt=6,
        )
    )
    heading_3: HeadingStyleProfile = Field(
        default_factory=lambda: HeadingStyleProfile(
            uppercase=False,
            alignment="left",
            first_line_indent_cm=1.25,
            spacing_before_pt=10,
            spacing_after_pt=4,
        )
    )
    heading_4: HeadingStyleProfile = Field(
        default_factory=lambda: HeadingStyleProfile(
            uppercase=False,
            italic=True,
            alignment="left",
            first_line_indent_cm=1.25,
            spacing_before_pt=8,
            spacing_after_pt=2,
        )
    )
    figure: FigureStyleProfile = Field(default_factory=FigureStyleProfile)
    table: TableStyleProfile = Field(default_factory=TableStyleProfile)
    lists: ListStyleProfile = Field(default_factory=ListStyleProfile)
    # Резерв для расширений плагинов.
    extra: dict[str, Any] = Field(default_factory=dict)


class SectionsTemplate(BaseModel):
    name: str
    type: Literal["title", "frontmatter", "main", "appendix", "custom"]
    page_numbering: dict[str, Any] = Field(default_factory=dict)
    header: dict[str, Any] | None = None
    footer: dict[str, Any] | None = None


class CheckConfig(BaseModel):
    enabled: bool = True
    severity: Literal["error", "warning", "info"] | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class Profile(BaseModel):
    id: str
    name: str
    version: str = "1.0"
    extends: str | None = None
    based_on: list[str] = Field(default_factory=list)
    effective_from: str | None = None
    effective_until: str | None = None
    description: str = ""

    styles: StylesProfile = Field(default_factory=StylesProfile)
    sections_template: list[SectionsTemplate] = Field(default_factory=list)
    checks: dict[str, CheckConfig] = Field(default_factory=dict)


def _builtin_profiles_dir() -> Path:
    # Профили лежат в profiles/ корня репозитория. Для установленного пакета —
    # потребуется альтернативный механизм (importlib.resources).
    return Path(__file__).resolve().parents[3] / "profiles"


def load_profile(profile_id: str, search_paths: list[Path] | None = None) -> Profile:
    """Загрузить профиль по ID. Если есть `extends` — рекурсивно слить с родителем.

    Порядок поиска:

    1. Локальный реестр в БД (custom_profiles) — для установленных
       кафедральных профилей. Доступен, если модуль ``gostforge.db``
       импортируется и таблица существует.
    2. ``search_paths`` (по умолчанию — каталог встроенных профилей).
    """
    # 1. Сначала смотрим в БД (custom-профили перекрывают builtin
    # для одноимённого id — это позволяет кафедре переопределить
    # параметры базового стандарта).
    custom_yaml = _load_from_db(profile_id)
    if custom_yaml is not None:
        data = yaml.safe_load(custom_yaml)
        profile = Profile(**data)
        if profile.extends:
            parent = load_profile(profile.extends, search_paths)
            profile = _merge_profile(parent, profile)
        return profile

    # 2. Файловые профили.
    search_paths = search_paths or [_builtin_profiles_dir()]
    for path in search_paths:
        candidate = path / f"{profile_id}.yaml"
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
            profile = Profile(**data)
            if profile.extends:
                parent = load_profile(profile.extends, search_paths)
                profile = _merge_profile(parent, profile)
            return profile

    raise FileNotFoundError(f"Profile '{profile_id}' not found in {search_paths}")


def list_profiles(search_paths: list[Path] | None = None) -> list[str]:
    """Список ID доступных профилей (builtin + установленные в БД)."""
    search_paths = search_paths or [_builtin_profiles_dir()]
    ids: set[str] = set()
    for path in search_paths:
        if not path.exists():
            continue
        for f in path.glob("*.yaml"):
            ids.add(f.stem)
    # Добавляем профили из БД.
    ids |= set(_list_db_profile_ids())
    return sorted(ids)


def _load_from_db(profile_id: str) -> str | None:
    """Прочитать YAML кастомного профиля из БД (None если нет или БД недоступна).

    Помещён в отдельную функцию с try/except, чтобы:
      * избежать циклической зависимости gostforge.profile ↔ gostforge.db
        (импорт ленивый, внутри функции);
      * не валить весь load_profile, если БД недоступна (нет прав, нет
        каталога) — fallback на файловые профили.
    """
    try:
        from gostforge.db import get_connection, get_custom_profile
    except ImportError:
        return None
    try:
        with get_connection() as conn:
            record = get_custom_profile(conn, profile_id)
            return record.yaml_content if record is not None else None
    except Exception:
        return None


def _list_db_profile_ids() -> list[str]:
    """ID всех custom-профилей из БД ([] если БД недоступна)."""
    try:
        from gostforge.db import get_connection, list_custom_profiles
    except ImportError:
        return []
    try:
        with get_connection() as conn:
            return [p.profile_id for p in list_custom_profiles(conn)]
    except Exception:
        return []


def is_custom_profile(profile_id: str) -> bool:
    """True если профиль установлен в локальном реестре (а не builtin)."""
    return _load_from_db(profile_id) is not None


def _deep_merge(parent: Any, child: Any) -> Any:
    """Рекурсивное слияние словарей.

    - dict: ключи объединяются, child перебивает parent при совпадении.
    - list: child заменяет parent целиком (если непустой); пустой list child
      означает «использовать родительский».
    - скаляры: child перебивает parent, если он не None.
    """
    if isinstance(parent, dict) and isinstance(child, dict):
        merged: dict[str, Any] = dict(parent)
        for key, child_value in child.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], child_value)
            else:
                merged[key] = child_value
        return merged
    if isinstance(parent, list) and isinstance(child, list):
        return child if child else parent
    return child if child is not None else parent


# Поля, которые должны браться у ребёнка как есть (не сливаются),
# потому что идентифицируют сам профиль.
_CHILD_OVERRIDE_FIELDS = {"id", "name", "version", "extends", "effective_from",
                          "effective_until"}


def _merge_profile(parent: Profile, child: Profile) -> Profile:
    """Глубокое слияние: child переопределяет parent поле-в-поле.

    Работает через `model_dump()`, чтобы единообразно обходить вложенные
    pydantic-модели, dict-поля (`styles.extra`, `checks[*].params`) и списки.
    """
    parent_data = parent.model_dump()
    child_data = child.model_dump(exclude_unset=True)

    merged_data = _deep_merge(parent_data, child_data)

    # Эти поля всегда идут от ребёнка, даже если он их не задал явно
    # (model_dump(exclude_unset=True) их пропустит).
    for f in _CHILD_OVERRIDE_FIELDS:
        value = getattr(child, f)
        if value is not None:
            merged_data[f] = value

    # description: непустое значение ребёнка перебивает родителя.
    if child.description:
        merged_data["description"] = child.description

    return Profile(**merged_data)
