# ruff: noqa: RUF002

"""Движок автоисправлений.

Каждый фиксер — функция вида:
    def fixer(model: Document, profile: Profile) -> list[FixApplied]

Фиксер регистрируется по своему коду (T.08, H.03 и т.д.) в реестре.
Engine читает из профиля, какие фиксеры включены, и вызывает их по очереди,
мутируя документ на месте.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from gostforge.model import Document
from gostforge.profile import Profile


@dataclass
class FixApplied:
    """Запись о применённой автоправке."""

    fixer_code: str  # код проверки (T.08, H.03, ...)
    location: str  # путь в модели до изменённого узла
    description: str  # человекочитаемое описание правки
    details: dict[str, str] = field(default_factory=dict)


# Фиксеры МУТИРУЮТ Document на месте и возвращают список применённых правок.
FixerFn = Callable[[Document, Profile], list[FixApplied]]

_registry: dict[str, FixerFn] = {}


def register(code: str) -> Callable[[FixerFn], FixerFn]:
    """Декоратор для регистрации фиксера.

    Пример:
        @register("T.08")
        def fix_double_spaces(model: Document, profile: Profile) -> list[FixApplied]:
            ...
    """

    def decorator(fn: FixerFn) -> FixerFn:
        if code in _registry:
            raise ValueError(f"Fixer '{code}' already registered")
        _registry[code] = fn
        return fn

    return decorator


def fix(
    document: Document,
    profile: Profile,
    codes: Iterable[str] | None = None,
) -> list[FixApplied]:
    """Применить все зарегистрированные фиксеры к document.

    Если `codes` задан — применяются только указанные фиксеры
    (даже если они выключены в профиле). Иначе — все включённые в профиле.

    Документ мутируется на месте.
    """
    applied: list[FixApplied] = []

    if codes is not None:
        wanted = list(codes)
    else:
        wanted = [code for code, cfg in profile.checks.items() if cfg.enabled]

    for code in wanted:
        fn = _registry.get(code)
        if fn is None:
            # Фиксер не реализован — молча пропускаем (как и в валидаторе).
            continue
        applied.extend(fn(document, profile))

    return applied


def registered_fixers() -> list[str]:
    """Список кодов всех зарегистрированных фиксеров."""
    return sorted(_registry.keys())


# Импорт самих фиксеров: их регистрация происходит при импорте модулей.
from . import fixers  # noqa: E402,F401
