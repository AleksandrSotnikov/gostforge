"""Эвристический парсер .docx в модель документа.

Использует python-docx для базового разбора и lxml для нестандартных случаев
(колонтитулы, поля, ссылки). Работает эвристически: тип блока определяется
по стилю абзаца, паттернам в тексте, форматированию.

Поэтапная стратегия:
- Фаза 0: распознавать только параграфы и базовые свойства страницы
- Фаза 1: рисунки, таблицы, заголовки, нумерация
- Фаза 2: список литературы, перекрёстные ссылки, формулы
- Фаза 3: полный разбор колонтитулов, приложений
"""

from __future__ import annotations

from pathlib import Path

from gostforge.model import Document, DocumentMetadata


def parse_docx(path: str | Path) -> Document:
    """Прочитать .docx и вернуть модель документа.

    На фазе 0 — заглушка. Возвращает пустой Document с базовыми метаданными
    из docProps. Реальный разбор появится в фазе 0.5.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    # TODO (phase 0): извлечь метаданные из docProps/core.xml
    # TODO (phase 0): пройти по document.xml, построить параграфы
    # TODO (phase 1): распознать рисунки, таблицы, заголовки
    # TODO (phase 2): построить bibliography из последней секции «Список литературы»
    # TODO (phase 3): извлечь PageSection из sectPr с колонтитулами

    return Document(
        metadata=DocumentMetadata(title=path.stem),
    )
