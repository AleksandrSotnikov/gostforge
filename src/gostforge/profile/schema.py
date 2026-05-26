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


class StylesProfile(BaseModel):
    page: PageGeometryProfile = Field(default_factory=PageGeometryProfile)
    body: BodyTextProfile = Field(default_factory=BodyTextProfile)
    # ... другие стили: headings, captions, lists, tables, etc.
    extra: dict[str, Any] = Field(default_factory=dict)  # для расширений плагинов


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
