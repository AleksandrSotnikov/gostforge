# ruff: noqa: RUF002, RUF003
"""Inline-аннотация .docx: вставка пометок о нарушениях прямо в текст.

Это упрощённый вариант аннотации (Фаза 1). Вместо «настоящих» OOXML-комментариев
Word (которые требуют создания отдельной part `word/comments.xml`, relationship
и пары `<w:commentRangeStart/>` / `<w:commentReference/>`) мы вставляем в начало
проблемного параграфа inline-run с маркером вида `[CODE: message]`, выделенным
курсивом красным цветом.

Преподаватель видит пометки прямо в тексте — выноску на полях не получим,
но смысл «здесь нарушение» сохраняется. На Фазе 2 этот модуль заменим
на полноценные комментарии Word.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document as DocxDocument
from docx.shared import RGBColor

from gostforge.parser import parse_docx
from gostforge.profile import Profile
from gostforge.validator import validate
from gostforge.validator.engine import Violation

# RGB красного цвета для маркеров.
_MARKER_COLOR = RGBColor(0xC0, 0x00, 0x00)

# Локации, для которых не существует «настоящего» параграфа в документе —
# тогда маркер падает в первый параграф.
_DOCUMENT_LEVEL_PREFIXES = (
    "page_sections.",  # геометрия страницы, секции вёрстки
    "header.",
    "footer.",
    "metadata.",
    "bibliography.",
)

# Регулярки для извлечения идентификатора блока из location.
# Пример: "page_sections.main.children[3]" → не block-level.
# Пример: "paragraph.<id>" или "blocks.<id>" → block-level.
_BLOCK_ID_PATTERNS = (
    re.compile(r"paragraph[s]?\.([a-zA-Z0-9_\-]+)"),
    re.compile(r"figure[s]?\.([a-zA-Z0-9_\-]+)"),
    re.compile(r"table[s]?\.([a-zA-Z0-9_\-]+)"),
    re.compile(r"block[s]?\.([a-zA-Z0-9_\-]+)"),
)


def _extract_block_id(location: str) -> str | None:
    """Вытащить ID блока из location-строки, если он там есть."""
    for pattern in _BLOCK_ID_PATTERNS:
        match = pattern.search(location)
        if match:
            return match.group(1)
    return None


def _format_marker(violation: Violation) -> str:
    """Сформировать текст маркера для нарушения."""
    return f"[{violation.check_code}: {violation.message}]"


def _insert_marker_run(paragraph: object, text: str) -> None:
    """Вставить run с маркером в начало параграфа.

    Использует низкоуровневое API python-docx: создаёт новый run и
    переносит его в начало списка дочерних элементов параграфа.
    """
    # paragraph — это docx.text.paragraph.Paragraph; пользуемся его публичным
    # API add_run, затем «выкручиваем» получившийся <w:r> в начало <w:p>.
    run = paragraph.add_run(text + " ")  # type: ignore[attr-defined]
    run.italic = True
    run.font.color.rgb = _MARKER_COLOR

    # Переместить элемент run в начало <w:p>. Все существующие runs сдвинутся.
    p_elem = paragraph._element  # type: ignore[attr-defined]
    r_elem = run._element
    p_elem.remove(r_elem)
    # Вставить после <w:pPr>, если он есть; иначе в самое начало.
    ppr = p_elem.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr"
    )
    if ppr is not None:
        ppr.addnext(r_elem)
    else:
        p_elem.insert(0, r_elem)


def _is_document_level(location: str) -> bool:
    """Понять, относится ли нарушение к документу в целом, а не к блоку."""
    if not location:
        return True
    return any(location.startswith(prefix) for prefix in _DOCUMENT_LEVEL_PREFIXES)


def annotate_docx(
    input_path: str | Path,
    output_path: str | Path,
    profile: Profile,
) -> int:
    """Прогнать .docx через парсер и валидатор, записать копию с пометками.

    Под капотом:
    1. `parse_docx(input_path)` → Document
    2. `validate(doc, profile)` → list[Violation]
    3. Открыть `input_path` через python-docx напрямую (не через нашу модель),
       чтобы сохранить всё исходное форматирование.
    4. Для каждого Violation, у которого location ссылается на блок документа,
       найти соответствующий параграф и вставить inline-маркер.
       Для violations уровня документа маркер падает в первый параграф.
    5. Сохранить в output_path.

    Возвращает число вставленных маркеров.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    model = parse_docx(input_path)
    violations = validate(model, profile)

    docx_doc = DocxDocument(str(input_path))
    paragraphs = list(docx_doc.paragraphs)

    if not paragraphs:
        # Документ без параграфов — создаём один пустой, чтобы было куда писать.
        docx_doc.add_paragraph("")
        paragraphs = list(docx_doc.paragraphs)

    # Индекс id-блока → параграф. На Фазе 0 парсер не присваивает ID, поэтому
    # такой индекс почти всегда пустой; держим его на будущее.
    blocks_by_id: dict[str, object] = {}
    for ps in model.page_sections:
        for child in ps.content:
            block_id = getattr(child, "id", None)
            if isinstance(block_id, str) and block_id:
                blocks_by_id[block_id] = child

    inserted = 0
    for violation in violations:
        target_paragraph: object | None = None

        block_id = _extract_block_id(violation.location)
        if block_id and block_id in blocks_by_id:
            # На будущее: когда парсер начнёт присваивать ID, понадобится
            # отображение из ID модели в реальный параграф docx. Пока что
            # такого отображения нет, поэтому проваливаемся в fallback.
            target_paragraph = None

        if target_paragraph is None:
            # Fallback: уровень документа или ID не разрешился — в первый параграф.
            if _is_document_level(violation.location) or block_id is None:
                target_paragraph = paragraphs[0]
            else:
                target_paragraph = paragraphs[0]

        _insert_marker_run(target_paragraph, _format_marker(violation))
        inserted += 1

    docx_doc.save(str(output_path))
    return inserted
