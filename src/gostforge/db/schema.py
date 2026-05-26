"""Структуры данных для БД (dataclass-обёртки над строками таблиц)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ViolationRecord:
    """Одно нарушение, записанное в БД (отличается от Violation тем, что
    содержит id и FK на submission)."""

    code: str
    severity: str
    message: str
    location: str = ""
    suggestion: str = ""
    id: int | None = None
    submission_id: int | None = None


@dataclass
class Submission:
    """Запись о проверке файла: метаданные + summary + список violations.

    Поля счётчиков (error_count, warning_count, info_count) денормализованы
    для быстрых выборок «история проверок» без JOIN. При записи через
    record_submission заполняются автоматически из списка violations.
    """

    filename: str
    profile_id: str
    created_at: str  # ISO 8601
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    violations: list[ViolationRecord] = field(default_factory=list)
    id: int | None = None
