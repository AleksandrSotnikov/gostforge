"""Экспорт модели документа в .docx с применением стилей профиля.

Особое внимание — корректной генерации:
- sectPr со ссылками на отдельные header/footer-part для каждой PageSection
- Полей PAGE/NUMPAGES/STYLEREF для динамики в колонтитулах
- Перекрёстных ссылок
- Подписей рисунков и таблиц с автонумерацией
"""

from __future__ import annotations

from pathlib import Path

from gostforge.model import Document
from gostforge.profile import Profile


def export_docx(document: Document, profile: Profile, output_path: str | Path) -> None:
    """Собрать .docx из модели по профилю.

    На фазе 0 — заглушка. Полная реализация в фазах 0.5–2.
    """
    output_path = Path(output_path)

    # TODO (phase 0): создать минимальный docx с правильными полями и шрифтом
    # TODO (phase 0): применить стили заголовков из профиля
    # TODO (phase 1): экспортировать таблицы, рисунки с подписями
    # TODO (phase 1): сквозная нумерация рисунков и таблиц
    # TODO (phase 2): генерация sectPr для каждой PageSection
    # TODO (phase 2): отдельные header/footer-part с разорванным link-to-previous
    # TODO (phase 2): поля PAGE и STYLEREF в колонтитулах
    # TODO (phase 3): формулы (OMML), bibliography по 7.0.100, перекрёстные ссылки

    raise NotImplementedError("Exporter — фаза 0.5, ещё в работе")
