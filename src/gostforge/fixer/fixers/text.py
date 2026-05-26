# ruff: noqa: RUF001, RUF002, RUF003

"""T.* — фиксеры основного текста."""

from __future__ import annotations

import re

from gostforge.model import (
    Block,
    Document,
    LogicalSection,
    Paragraph,
    TextRun,
)
from gostforge.profile import Profile

from ..engine import FixApplied, register

# Регексп множественных пробелов (два и более подряд).
_DOUBLE_SPACE_RE = re.compile(r"  +")

# Шаблон " - " (пробел–дефис–пробел) для замены на длинное тире.
_HYPHEN_BETWEEN_SPACES = " - "
_EM_DASH_BETWEEN_SPACES = " — "

# Неразрывный пробел (U+00A0). Используется фиксерами T.12 и T.13.
_NBSP = " "

# T.12: между числом и единицей измерения. Шаблон зеркален regex'у
# проверки `check_nbsp_between_number_and_unit` в validator/checks/text.py,
# но без `(?<!\d)` — нам важно лишь поймать «число + обычный пробел + единица»
# в пределах одного TextRun. Список единиц соответствует `_DEFAULT_UNITS`
# из валидатора; держим их синхронно вручную, чтобы не плодить cross-импорты.
_NUMBER_UNIT_RE = re.compile(
    r"(\b\d+(?:[.,]\d+)?) (г|кг|мг|т|м|см|мм|км|л|мл|ч|мин|с|°C|%|шт|руб|год|лет)\b"
)

# T.13: между двумя инициалами и фамилией. Захватываем три группы, чтобы
# в re.sub собрать строку обратно с NBSP вместо обычного пробела.
_INITIALS_SURNAME_RE = re.compile(r"([А-ЯЁ]\.)\s([А-ЯЁ]\.)\s([А-ЯЁ][а-яё]+)")


def _iter_paragraphs(items: list[LogicalSection | Block]) -> list[Paragraph]:
    """Рекурсивно собрать все Paragraph из списка вложенных элементов модели."""
    result: list[Paragraph] = []
    for item in items:
        if isinstance(item, Paragraph):
            result.append(item)
        elif isinstance(item, LogicalSection):
            result.extend(_iter_paragraphs(item.children))
    return result


def _all_paragraphs(document: Document) -> list[Paragraph]:
    """Все Paragraph из всех PageSection документа (рекурсивный обход).

    Хелпер продублирован из `validator.checks.text._all_paragraphs`, чтобы
    не плодить циклические зависимости между фиксером и валидатором.
    """
    paragraphs: list[Paragraph] = []
    for section in document.page_sections:
        paragraphs.extend(_iter_paragraphs(section.content))
    return paragraphs


def _text_runs(paragraph: Paragraph) -> list[TextRun]:
    """Только TextRun-ы из содержимого параграфа (CrossRef отфильтровываются)."""
    return [el for el in paragraph.content if isinstance(el, TextRun)]


def _paragraph_location(paragraph: Paragraph) -> str:
    """Стандартный путь в модели для FixApplied.location."""
    return f"page_sections.*.paragraph[{paragraph.id}]"


@register("T.08")
def fix_double_spaces(document: Document, profile: Profile) -> list[FixApplied]:
    """Заменить два и более пробелов подряд на одинарный.

    Работает в пределах одного TextRun. Случай, когда серия пробелов
    пересекает границу TextRun, на Фазе 1 не обрабатывается — это редкая
    патология форматирования.
    """
    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        paragraph_changed = False
        for run in _text_runs(paragraph):
            if not run.text:
                continue
            new_text = _DOUBLE_SPACE_RE.sub(" ", run.text)
            if new_text != run.text:
                run.text = new_text
                paragraph_changed = True
        if paragraph_changed:
            applied.append(
                FixApplied(
                    fixer_code="T.08",
                    location=_paragraph_location(paragraph),
                    description="Заменены двойные пробелы на одинарные",
                )
            )
    return applied


@register("T.09")
def fix_trailing_whitespace(document: Document, profile: Profile) -> list[FixApplied]:
    """Удалить хвостовые пробельные символы в конце параграфа.

    Пробелы между TextRun-ами в середине параграфа не трогаются — обрезается
    только самый последний непустой TextRun (через `.rstrip()`).
    """
    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        runs = _text_runs(paragraph)
        last_run: TextRun | None = None
        for run in runs:
            if run.text:
                last_run = run
        if last_run is None:
            continue
        stripped = last_run.text.rstrip()
        if stripped != last_run.text:
            last_run.text = stripped
            applied.append(
                FixApplied(
                    fixer_code="T.09",
                    location=_paragraph_location(paragraph),
                    description="Удалены хвостовые пробелы в конце абзаца",
                )
            )
    return applied


# Конечный автомат для парных кавычек. Состояния:
#   "outside" — ожидаем открывающую,
#   "inside" — ожидаем закрывающую.
_OPENING_QUOTE = "«"  # «
_CLOSING_QUOTE = "»"  # »


def _replace_paired_quotes(text: str) -> tuple[str, bool]:
    """Заменить пары ASCII-кавычек `"..."` на «...».

    Если количество кавычек нечётное (есть непарная) — возвращаем исходный
    текст без изменений, чтобы не сломать смысл.
    """
    if text.count('"') == 0:
        return text, False
    if text.count('"') % 2 != 0:
        return text, False

    out: list[str] = []
    inside = False
    for ch in text:
        if ch == '"':
            if not inside:
                out.append(_OPENING_QUOTE)
                inside = True
            else:
                out.append(_CLOSING_QUOTE)
                inside = False
        else:
            out.append(ch)
    new_text = "".join(out)
    return new_text, new_text != text


@register("T.10")
def fix_straight_quotes(document: Document, profile: Profile) -> list[FixApplied]:
    """Заменить парные прямые кавычки `"..."` на «ёлочки» «...».

    На Фазе 1 применяется только к параграфам, состоящим из одного непустого
    TextRun. Для нескольких TextRun-ов (с разным форматированием внутри
    кавычек) пропускаем — корректная склейка с сохранением форматирования
    запланирована на Фазу 2.
    """
    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        runs = _text_runs(paragraph)
        non_empty = [r for r in runs if r.text]
        if len(non_empty) != 1:
            continue
        run = non_empty[0]
        new_text, changed = _replace_paired_quotes(run.text)
        if changed:
            run.text = new_text
            applied.append(
                FixApplied(
                    fixer_code="T.10",
                    location=_paragraph_location(paragraph),
                    description="Прямые кавычки заменены на «ёлочки»",
                )
            )
    return applied


@register("T.11")
def fix_hyphen_to_dash(document: Document, profile: Profile) -> list[FixApplied]:
    """Заменить « - » (пробел–дефис–пробел) на « — » (длинное тире, U+2014).

    Как и T.10, на Фазе 1 применяется только к параграфам с одним непустым
    TextRun, чтобы не ломать форматирование между несколькими run-ами.
    """
    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        runs = _text_runs(paragraph)
        non_empty = [r for r in runs if r.text]
        if len(non_empty) != 1:
            continue
        run = non_empty[0]
        if _HYPHEN_BETWEEN_SPACES not in run.text:
            continue
        new_text = run.text.replace(_HYPHEN_BETWEEN_SPACES, _EM_DASH_BETWEEN_SPACES)
        if new_text != run.text:
            run.text = new_text
            applied.append(
                FixApplied(
                    fixer_code="T.11",
                    location=_paragraph_location(paragraph),
                    description="Дефис между пробелами заменён на длинное тире",
                )
            )
    return applied


@register("T.12")
def fix_unit_nbsp(document: Document, profile: Profile) -> list[FixApplied]:
    """Заменить обычный пробел между числом и единицей измерения на NBSP.

    Работает в пределах одного TextRun: при склейке текста через несколько
    run-ов число и единица могут попасть в разные run-ы, и regex это не
    поймает — такой случай намеренно оставлен на следующую фазу.

    Видимо текст не меняется: U+00A0 неотличим глазом от обычного пробела,
    но запрещает разрыв строки между числом и единицей.
    """
    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        paragraph_changed = False
        for run in _text_runs(paragraph):
            if not run.text:
                continue
            new_text = _NUMBER_UNIT_RE.sub(rf"\1{_NBSP}\2", run.text)
            if new_text != run.text:
                run.text = new_text
                paragraph_changed = True
        if paragraph_changed:
            applied.append(
                FixApplied(
                    fixer_code="T.12",
                    location=_paragraph_location(paragraph),
                    description=(
                        "Обычные пробелы между числом и единицей измерения заменены на неразрывные"
                    ),
                )
            )
    return applied


@register("T.13")
def fix_initials_nbsp(document: Document, profile: Profile) -> list[FixApplied]:
    """Заменить обычные пробелы между инициалами и фамилией на NBSP.

    «И. И. Иванов» → «И.<NBSP>И.<NBSP>Иванов». Видимо текст не меняется —
    меняется только разрыв строки: NBSP запрещает перенос между инициалами
    и фамилией.
    """
    applied: list[FixApplied] = []
    for paragraph in _all_paragraphs(document):
        paragraph_changed = False
        for run in _text_runs(paragraph):
            if not run.text:
                continue
            new_text = _INITIALS_SURNAME_RE.sub(rf"\1{_NBSP}\2{_NBSP}\3", run.text)
            if new_text != run.text:
                run.text = new_text
                paragraph_changed = True
        if paragraph_changed:
            applied.append(
                FixApplied(
                    fixer_code="T.13",
                    location=_paragraph_location(paragraph),
                    description=(
                        "Обычные пробелы между инициалами и фамилией заменены на неразрывные"
                    ),
                )
            )
    return applied


@register("T.06")
def fix_disable_auto_hyphenation(
    document: Document,
    profile: Profile,  # noqa: ARG001
) -> list[FixApplied]:
    """Отключить автоматический перенос слов (`Document.auto_hyphenation = False`).

    Эта правка безопасна: запрет автопереносов не меняет видимый текст,
    только разбивку строк, которая по ГОСТ должна делаться вручную.
    """
    if document.auto_hyphenation is True:
        document.auto_hyphenation = False
        return [
            FixApplied(
                fixer_code="T.06",
                location="document.auto_hyphenation",
                description="Автоматический перенос слов отключён",
            )
        ]
    return []


@register("T.07")
def fix_consecutive_empty_paragraphs(document: Document, profile: Profile) -> list[FixApplied]:
    """Удалить лишние подряд идущие пустые абзацы.

    Параметр `checks.T.07.params.max_consecutive_empty: int = 1` —
    максимально допустимое число пустых абзацев подряд. Лишние удаляются.
    """
    config = profile.checks.get("T.07")
    max_empty = 1
    if config and config.params.get("max_consecutive_empty") is not None:
        max_empty = int(config.params["max_consecutive_empty"])

    applied: list[FixApplied] = []

    def _is_empty(p: object) -> bool:
        if not isinstance(p, Paragraph):
            return False
        return not any(isinstance(r, TextRun) and r.text and r.text.strip() for r in p.content)

    def _clean_container(
        items: list[LogicalSection | Block],
        container_path: str,
    ) -> None:
        new_items: list[LogicalSection | Block] = []
        empty_streak = 0
        for item in items:
            if isinstance(item, LogicalSection):
                _clean_container(item.children, f"{container_path}.{item.id}")
                new_items.append(item)
                empty_streak = 0
            elif _is_empty(item):
                empty_streak += 1
                if empty_streak <= max_empty:
                    new_items.append(item)
                else:
                    applied.append(
                        FixApplied(
                            fixer_code="T.07",
                            location=f"{container_path}.paragraph[{item.id}]",
                            description="Удалён лишний пустой абзац подряд",
                        )
                    )
            else:
                new_items.append(item)
                empty_streak = 0
        items[:] = new_items

    for ps in document.page_sections:
        _clean_container(ps.content, f"page_sections.{ps.id}")

    return applied


# Стили параграфов, которые считаются «телом» и подлежат правкам T.03/T.04/T.05.
# Заголовки, подписи и колонтитулы имеют свои правила и не трогаются.
_BODY_EXCLUDE_PREFIXES = (
    "heading",
    "caption",
    "image caption",
    "table caption",
    "figure caption",
    "title",
    "subtitle",
    "footnote",
    "header",
    "footer",
)


def _is_body_paragraph(paragraph: Paragraph) -> bool:
    """True, если параграф относится к основному тексту (не heading/caption/etc)."""
    style = (paragraph.style_name or "").strip().lower()
    if not style or style == "normal" or style.startswith("body"):
        return True
    return not any(style.startswith(p) for p in _BODY_EXCLUDE_PREFIXES)


@register("T.03")
def fix_line_spacing(document: Document, profile: Profile) -> list[FixApplied]:
    """Привести межстрочный интервал основного текста к profile.styles.body.line_spacing.

    Безопасно: меняет только визуальное расстояние между строками,
    не текст. Параграфы с line_spacing=None пропускаются (наследуется
    от стиля).
    """
    expected = float(profile.styles.body.line_spacing)
    applied: list[FixApplied] = []
    for p in _all_paragraphs(document):
        if not _is_body_paragraph(p):
            continue
        if p.line_spacing is None:
            continue
        if abs(p.line_spacing - expected) <= 0.01:
            continue
        old = p.line_spacing
        p.line_spacing = expected
        applied.append(
            FixApplied(
                fixer_code="T.03",
                location=_paragraph_location(p),
                description=(f"Межстрочный интервал {old} → {expected}"),
            )
        )
    return applied


@register("T.04")
def fix_first_line_indent(document: Document, profile: Profile) -> list[FixApplied]:
    """Привести отступ красной строки основного текста к
    profile.styles.body.first_line_indent_cm.

    Параграфы с first_line_indent_cm=None пропускаются (наследуется).
    """
    expected = float(profile.styles.body.first_line_indent_cm)
    applied: list[FixApplied] = []
    for p in _all_paragraphs(document):
        if not _is_body_paragraph(p):
            continue
        if p.first_line_indent_cm is None:
            continue
        if abs(p.first_line_indent_cm - expected) <= 0.05:
            continue
        old = p.first_line_indent_cm
        p.first_line_indent_cm = expected
        applied.append(
            FixApplied(
                fixer_code="T.04",
                location=_paragraph_location(p),
                description=f"Отступ красной строки {old} → {expected} см",
            )
        )
    return applied


@register("T.05")
def fix_paragraph_alignment(document: Document, profile: Profile) -> list[FixApplied]:
    """Привести выравнивание основного текста к profile.styles.body.alignment.

    По умолчанию для ГОСТ 7.32 — justify (по ширине). Меняем только
    body-параграфы; заголовки и подписи имеют свои правила.
    """
    expected = profile.styles.body.alignment
    applied: list[FixApplied] = []
    for p in _all_paragraphs(document):
        if not _is_body_paragraph(p):
            continue
        if p.alignment is None:
            continue
        if p.alignment == expected:
            continue
        old = p.alignment
        p.alignment = expected
        applied.append(
            FixApplied(
                fixer_code="T.05",
                location=_paragraph_location(p),
                description=f"Выравнивание «{old}» → «{expected}»",
            )
        )
    return applied


@register("T.14")
def fix_paragraph_spacing(document: Document, profile: Profile) -> list[FixApplied]:
    """Привести интервалы между абзацами к profile.styles.body.

    Исправление симметрично проверке T.14: для каждого Normal-параграфа
    с явно заданным space_before_pt/space_after_pt != expected
    заменяем на expected (по умолчанию 0). Heading*/Caption/List*
    пропускаем.
    """
    body = profile.styles.body
    expected_before = float(body.space_before_pt)
    expected_after = float(body.space_after_pt)
    tolerance = 0.5
    config = profile.checks.get("T.14")
    if config:
        if config.params.get("expected_before_pt") is not None:
            expected_before = float(config.params["expected_before_pt"])
        if config.params.get("expected_after_pt") is not None:
            expected_after = float(config.params["expected_after_pt"])
        if config.params.get("tolerance_pt") is not None:
            tolerance = float(config.params["tolerance_pt"])

    applied: list[FixApplied] = []
    for p in _all_paragraphs(document):
        style = (p.style_name or "Normal").lower()
        if any(
            style.startswith(prefix)
            for prefix in ("heading", "caption", "list", "footer", "header", "title")
        ):
            continue
        if p.space_before_pt is not None and abs(p.space_before_pt - expected_before) > tolerance:
            old = p.space_before_pt
            p.space_before_pt = expected_before
            applied.append(
                FixApplied(
                    fixer_code="T.14",
                    location=_paragraph_location(p) + ".space_before_pt",
                    description=f"space_before {old:g} pt → {expected_before:g} pt",
                )
            )
        if p.space_after_pt is not None and abs(p.space_after_pt - expected_after) > tolerance:
            old = p.space_after_pt
            p.space_after_pt = expected_after
            applied.append(
                FixApplied(
                    fixer_code="T.14",
                    location=_paragraph_location(p) + ".space_after_pt",
                    description=f"space_after {old:g} pt → {expected_after:g} pt",
                )
            )
    return applied


__all__ = [
    "fix_consecutive_empty_paragraphs",
    "fix_disable_auto_hyphenation",
    "fix_double_spaces",
    "fix_first_line_indent",
    "fix_hyphen_to_dash",
    "fix_initials_nbsp",
    "fix_line_spacing",
    "fix_paragraph_alignment",
    "fix_paragraph_spacing",
    "fix_straight_quotes",
    "fix_trailing_whitespace",
    "fix_unit_nbsp",
]
