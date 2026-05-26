"""Движок валидатора.

Каждая проверка — функция вида:
    def check(model: Document, profile: Profile) -> list[Violation]

Проверки регистрируются по своему коду (F.01, T.02 и т.д.) в реестре.
Engine читает из профиля, какие проверки включены, и вызывает их по очереди.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from gostforge.model import Document
from gostforge.profile import Profile


Severity = Literal["error", "warning", "info"]


@dataclass
class Violation:
    """Найденное нарушение."""

    check_code: str
    severity: Severity
    message: str
    # Путь в модели, ведущий к проблемному узлу (для аннотирования и UI)
    location: str = ""
    # Опциональное предложение по исправлению
    suggestion: str = ""
    # Опциональные параметры для отчёта (например, ожидаемое/найденное значение)
    details: dict[str, str] = field(default_factory=dict)


CheckFn = Callable[[Document, Profile], list[Violation]]

_registry: dict[str, CheckFn] = {}


def register(code: str) -> Callable[[CheckFn], CheckFn]:
    """Декоратор для регистрации проверки.

    Пример:
        @register("F.01")
        def check_margins(model: Document, profile: Profile) -> list[Violation]:
            ...
    """

    def decorator(fn: CheckFn) -> CheckFn:
        if code in _registry:
            raise ValueError(f"Check '{code}' already registered")
        _registry[code] = fn
        return fn

    return decorator


def validate(document: Document, profile: Profile) -> list[Violation]:
    """Прогнать документ через все включённые в профиле проверки."""
    violations: list[Violation] = []
    for code, config in profile.checks.items():
        if not config.enabled:
            continue
        fn = _registry.get(code)
        if fn is None:
            # Проверка указана в профиле, но не реализована — пропускаем
            # с warning'ом для пользователя (логируется CLI-уровнем).
            continue
        violations.extend(fn(document, profile))
    return violations


def registered_checks() -> list[str]:
    """Список кодов всех зарегистрированных проверок."""
    return sorted(_registry.keys())


# Импорт самих проверок: их регистрация происходит при импорте модулей
from . import checks  # noqa: E402,F401

# Загружаем пользовательские плагины из ~/.gostforge/plugins/. Импорт
# плагинов идёт через декораторы @register, описанные выше. Любой плагин
# с битым кодом логируется и пропускается без падения валидатора.
from gostforge.plugins import load_plugins as _load_plugins  # noqa: E402

_load_plugins()
