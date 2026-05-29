"""Движок валидатора.

Каждая проверка — функция вида:
    def check(model: Document, profile: Profile) -> list[Violation]

Проверки регистрируются по своему коду (F.01, T.02 и т.д.) в реестре.
Engine читает из профиля, какие проверки включены, и вызывает их по очереди.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

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
    """Прогнать документ через все включённые в профиле проверки.

    Дополнительно фильтрует нарушения по ``LogicalSection.disabled_checks``:
    если раздел отметил конкретный код или ``"*"`` как «отключённый» —
    нарушения с location, содержащим id этой секции, выбрасываются.
    Это поддержка конструктора: студент может пометить «титульный лист»
    или «приложения» как разделы, к которым стандарт ГОСТа не
    применяется.
    """
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
    return _filter_disabled_section_violations(document, violations)


ValidateEvent = tuple[Literal["check"], str, int, int] | tuple[Literal["done"], list[Violation]]


def validate_iter(document: Document, profile: Profile) -> Iterator[ValidateEvent]:
    """Generator-вариант :func:`validate`: yields события прогресса.

    Используется streaming-эндпоинтами (SSE) и live-UI, которые
    хотят показать прогресс длинной проверки. Семантика идентична
    `validate` — фильтр disabled_checks применяется в финале.

    События:

    * ``("check", code, index, total)`` — перед запуском проверки
      ``code`` (zero-based ``index`` из ``total`` включённых).
      Клиент использует это для процент-бара.
    * ``("done", violations)`` — отфильтрованный финальный список
      нарушений. Гарантированно последнее событие.
    """
    enabled = [(code, cfg) for code, cfg in profile.checks.items() if cfg.enabled]
    total = len(enabled)
    violations: list[Violation] = []
    for i, (code, _cfg) in enumerate(enabled):
        yield ("check", code, i, total)
        fn = _registry.get(code)
        if fn is None:
            continue
        violations.extend(fn(document, profile))
    yield ("done", _filter_disabled_section_violations(document, violations))


def _filter_disabled_section_violations(
    document: Document, violations: list[Violation]
) -> list[Violation]:
    """Отфильтровать violations, попадающие в LogicalSection.disabled_checks.

    Алгоритм:
    1. Собрать карту section_id → set(disabled_codes), включая поддержку
       спецзначения ``"*"`` (отключить все).
    2. Для каждой violation: если location содержит id какой-то секции,
       и эта секция отключила код violation (или все коды) — выбросить.

    Сложность O(V * S), где V = число violations, S = число секций.
    На реальном документе оба значения < 100 → производительность OK.
    """
    disabled_map = _collect_disabled_checks(document)
    if not disabled_map:
        return violations
    result: list[Violation] = []
    for v in violations:
        if _is_violation_suppressed(v, disabled_map):
            continue
        result.append(v)
    return result


def _collect_disabled_checks(document: Document) -> dict[str, set[str]]:
    """Собрать карту section_id → set отключённых кодов проверок."""
    out: dict[str, set[str]] = {}

    def walk(items: list[Any]) -> None:
        for item in items:
            from gostforge.model import LogicalSection

            if isinstance(item, LogicalSection):
                if item.disabled_checks:
                    out[item.id] = set(item.disabled_checks)
                walk(item.children)

    for ps in document.page_sections:
        walk(ps.content)
    return out


def _is_violation_suppressed(violation: Violation, disabled_map: dict[str, set[str]]) -> bool:
    """True, если location violation указывает на секцию,
    отключившую этот код или все коды («*»)."""
    location = violation.location or ""
    for section_id, disabled in disabled_map.items():
        if section_id not in location:
            continue
        if "*" in disabled or violation.check_code in disabled:
            return True
    return False


def registered_checks() -> list[str]:
    """Список кодов всех зарегистрированных проверок."""
    return sorted(_registry.keys())


# Импорт самих проверок: их регистрация происходит при импорте модулей
# Загружаем пользовательские плагины из ~/.gostforge/plugins/. Импорт
# плагинов идёт через декораторы @register, описанные выше. Любой плагин
# с битым кодом логируется и пропускается без падения валидатора.
from gostforge.plugins import load_plugins as _load_plugins  # noqa: E402

from . import checks  # noqa: E402,F401

_load_plugins()
