"""Fluent-builder верхнего уровня для построения работы по ГОСТу.

Высокоуровневый API над моделью документа: студент собирает работу из
разделов и параграфов, а конструктор сам ставит правильные поля,
колонтитулы, нумерацию страниц и `page_break_before` у заголовков.
"""

from __future__ import annotations

import contextlib
import itertools
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from gostforge.model import (
    BibliographyEntry,
    Block,
    ContentTemplate,
    Document,
    DocumentMetadata,
    HeaderConfig,
    LogicalSection,
    PageGeometry,
    PageNumberingConfig,
    PageSection,
    Paragraph,
    TextRun,
)

from .section_builder import SectionBuilder, _heading_text

if TYPE_CHECKING:
    from gostforge.profile import Profile


NumberingMode = Literal["continuous", "by_chapter"]
WorkType = Literal["coursework", "bachelor_thesis", "master_thesis", "research_report", "other"]


# Алиасы заголовков раздела «Список использованных источников» — используются
# в build() для пост-обработки в Document.bibliography.
_BIBLIOGRAPHY_HEADINGS: frozenset[str] = frozenset(
    {
        "список использованных источников",
        "список литературы",
        "библиографический список",
        "список источников",
    }
)


class WorkBuilder:
    """Fluent API верхнего уровня. Возвращает SectionBuilder при `.section()`."""

    def __init__(
        self,
        title: str,
        author: str = "",
        year: int | None = None,
        work_type: WorkType = "coursework",
        profile_id: str = "gost-7.32-2017",
        *,
        supervisor: str = "",
        organization: str = "",
    ) -> None:
        self._title = title
        self._author = author
        self._year = year
        self._work_type: WorkType = work_type
        self._profile_id = profile_id
        self._supervisor = supervisor
        self._organization = organization

        # Верхнеуровневые логические разделы (level==1). Подразделы кладутся в
        # children этих разделов.
        self._sections: list[LogicalSection] = []
        self._active: SectionBuilder | None = None

        # Счётчики идентификаторов и нумерация рисунков/таблиц.
        self._id_counters: dict[str, itertools.count[int]] = {}
        self._figure_counter = itertools.count(1)
        self._table_counter = itertools.count(1)
        self._formula_counter = itertools.count(1)

        # Per-chapter счётчики и схема нумерации (из профиля).
        # Ключ — метка главы ("1", "2", "А", "Б", ...).
        self._figure_counters_by_chapter: dict[str, int] = {}
        self._table_counters_by_chapter: dict[str, int] = {}
        # Метка текущей главы, выставляется при каждом .section(...).
        # Пустая строка — фигура/таблица добавлены до первого раздела.
        self._current_chapter_label: str = ""
        self._is_current_chapter_appendix: bool = False
        # Счётчик обычных (не-приложений) глав — для нумерации «1», «2», ...
        # в режиме by_chapter.
        self._regular_chapter_counter = 0
        # Режимы нумерации и форматы подписей читаем лениво из профиля.
        (
            self._figure_numbering_mode,
            self._table_numbering_mode,
            self._figure_caption_format,
            self._table_caption_format,
        ) = _resolve_caption_settings_from_profile(profile_id)

    # --- Внутренние утилиты для SectionBuilder ------------------------------

    def _next_id(self, prefix: str) -> str:
        counter = self._id_counters.setdefault(prefix, itertools.count(1))
        return f"{prefix}-{next(counter)}"

    def _next_figure_number(self) -> int:
        return next(self._figure_counter)

    def _next_table_number(self) -> int:
        return next(self._table_counter)

    def _next_formula_number(self) -> int:
        return next(self._formula_counter)

    def _next_figure_label_with_ordinal(self) -> tuple[str, int]:
        """Метка для подписи рисунка + сквозной ordinal-номер.

        Метка зависит от схемы нумерации профиля и текущей главы:
        * приложение → «А.1», «А.2», «Б.1», ... (буква главы);
        * by_chapter (обычная глава) → «1.1», «1.2», ... (номер главы);
        * continuous либо нет текущей главы → «1», «2», ... .

        Ordinal — сквозной int независимо от схемы (1, 2, 3, ...) —
        используется как `Figure.number` для матчинга xref-ов по позиции.
        """
        ordinal = self._next_figure_number()
        chapter = self._current_chapter_label
        use_chapter = chapter and (
            self._is_current_chapter_appendix or self._figure_numbering_mode == "by_chapter"
        )
        if use_chapter:
            n = self._figure_counters_by_chapter.get(chapter, 0) + 1
            self._figure_counters_by_chapter[chapter] = n
            return f"{chapter}.{n}", ordinal
        return str(ordinal), ordinal

    def _next_table_label_with_ordinal(self) -> tuple[str, int]:
        """Зеркально к `_next_figure_label_with_ordinal`, но для таблиц."""
        ordinal = self._next_table_number()
        chapter = self._current_chapter_label
        use_chapter = chapter and (
            self._is_current_chapter_appendix or self._table_numbering_mode == "by_chapter"
        )
        if use_chapter:
            n = self._table_counters_by_chapter.get(chapter, 0) + 1
            self._table_counters_by_chapter[chapter] = n
            return f"{chapter}.{n}", ordinal
        return str(ordinal), ordinal

    def _set_active(self, builder: SectionBuilder) -> None:
        self._active = builder

    # --- Per-section override нумерации -------------------------------------

    @contextlib.contextmanager
    def numbering_override(
        self,
        *,
        figure: NumberingMode | None = None,
        table: NumberingMode | None = None,
    ) -> Iterator[None]:
        """Временно переопределить схему нумерации рисунков/таблиц.

        Полезен для разделов с нестандартной нумерацией: например,
        большая глава с по-главе-нумерацией внутри документа с глобальной
        сквозной схемой, или наоборот. После выхода из контекста режим
        восстанавливается.

        ``figure`` / ``table`` — желаемый режим (``"continuous"`` или
        ``"by_chapter"``) или ``None`` (не менять — оставить как в
        профиле). Сквозной ``ordinal`` (для xref) продолжает тикать
        независимо от режима, поэтому матчинг ссылок по позиции не
        ломается.

        Пример::

            with work_builder.numbering_override(figure="by_chapter"):
                sec_builder = work_builder.section("Большая глава")
                sec_builder.image("img.png", "Распределение")
                # Подпись: «Рисунок 1.1 — Распределение»
        """
        saved_fig = self._figure_numbering_mode
        saved_tbl = self._table_numbering_mode
        if figure is not None:
            self._figure_numbering_mode = figure
        if table is not None:
            self._table_numbering_mode = table
        try:
            yield
        finally:
            self._figure_numbering_mode = saved_fig
            self._table_numbering_mode = saved_tbl

    # --- Fluent API ----------------------------------------------------------

    def section(self, heading: str) -> SectionBuilder:
        """Добавить раздел 1 уровня и вернуть его SectionBuilder.

        Заголовок создаётся с атрибутами, удовлетворяющими H.01 для
        базового профиля ГОСТ 7.32: текст в верхнем регистре, bold,
        шрифт Times New Roman, кегль 14.
        """
        sec = LogicalSection(
            id=self._next_id("sec"),
            heading=[
                TextRun(
                    text=heading.upper(),
                    bold=True,
                    font="Times New Roman",
                    size_pt=14,
                )
            ],
            level=1,
        )
        self._sections.append(sec)
        # Обновляем контекст текущей главы для нумерации рисунков/таблиц.
        appendix_letter = _parse_appendix_letter(heading)
        if appendix_letter is not None:
            self._current_chapter_label = appendix_letter
            self._is_current_chapter_appendix = True
        else:
            self._regular_chapter_counter += 1
            self._current_chapter_label = str(self._regular_chapter_counter)
            self._is_current_chapter_appendix = False
        builder = SectionBuilder(self, sec)
        self._active = builder
        return builder

    # --- Терминальная сборка -------------------------------------------------

    def build(self) -> Document:
        """Собрать окончательную модель документа.

        - DocumentMetadata из аргументов __init__
        - Одна PageSection(type="main") с включённой нумерацией, footer="{page}"
          и start_value=3
        - У первого Paragraph каждой LogicalSection.level==1 (кроме самой
          первой) ставится page_break_before=True
        - Пост-обработка: если есть раздел «Список использованных источников»,
          его параграфы преобразуются в BibliographyEntry.
        """
        document = Document(
            profile_id=self._profile_id,
            metadata=DocumentMetadata(
                title=self._title,
                author=self._author,
                supervisor=self._supervisor,
                organization=self._organization,
                year=self._year,
                work_type=self._work_type,
            ),
        )

        # Разрыв страницы перед разделом level 1 ставится через
        # стиль Heading 1 (profile.styles.heading_1.page_break_before = True),
        # что применяется экспортёром через _apply_heading_styles.
        # Раньше тут проставлялся page_break_before=True на «первый
        # параграф» каждого раздела (кроме первого), но это давало баг
        # для глав без вступительного текста: если глава начиналась
        # сразу с подраздела 1.1 [текст], то page-break оседал на
        # первом параграфе ПОДРАЗДЕЛА, и текст уезжал на новую
        # страницу после заголовка 1.1. Удалено — стиль Heading 1
        # делает свою работу корректнее, без зависимости от наличия
        # параграфа сразу после заголовка.

        # Создаём одну PageSection «main». Параметры геометрии и нумерации
        # читаем из профиля (если он указан и зарегистрирован) — иначе
        # fallback на дефолты ГОСТ 7.32. Это закрывает F.01 (поля) и F.06
        # (start_value) для всех профилей-наследников (ЕСКД с правым полем
        # 10 мм, кафедра с start_value=4 и т. п.).
        page_margins, start_value = _resolve_page_params_from_profile(self._profile_id)
        page = PageGeometry(
            paper="A4",
            margins_mm=page_margins,
            orientation="portrait",
        )
        footer = HeaderConfig(
            default=ContentTemplate(center=[TextRun(text="{page}")]),
        )
        numbering = PageNumberingConfig(
            visible=True,
            format="arabic",
            start_mode="start_at",
            start_value=start_value,
        )
        content: list[LogicalSection | Block] = list(self._sections)
        page_section = PageSection(
            id="main",
            name="Основная часть",
            type="main",
            page=page,
            footer=footer,
            page_numbering=numbering,
            content=content,
        )
        document.page_sections.append(page_section)

        # Пост-обработка: вытаскиваем bibliography из раздела «Список ...».
        _extract_bibliography(document)

        return document

    def save(self, path: str | Path, profile: str | Profile | None = None) -> None:
        """Сборка + экспорт .docx.

        Сначала собирается модель, затем прогоняется через validator. Если
        обнаружены error-уровневые нарушения — поднимается ValueError со
        списком кодов нарушений.
        """
        # Поздний импорт — чтобы builder можно было использовать без побочных
        # зависимостей валидатора/экспортёра при описании модели.
        from gostforge.exporter import export_docx
        from gostforge.profile import Profile as _Profile
        from gostforge.profile import load_profile
        from gostforge.validator import validate

        document = self.build()

        resolved_profile: _Profile
        if profile is None:
            resolved_profile = load_profile(self._profile_id)
        elif isinstance(profile, str):
            resolved_profile = load_profile(profile)
        else:
            resolved_profile = profile

        # K.01 (структура PageSection-ов соответствует sections_template)
        # игнорируем при сохранении из builder: модель Фазы 1 кладёт всё в
        # одну main-секцию, тогда как профиль ожидает title/frontmatter/
        # appendix. Это будет исправлено в Фазе 2, когда builder начнёт
        # создавать полную структуру PageSection-ов. Включить обратно —
        # просто убрать фильтр.
        _IGNORED_BY_BUILDER = {"K.01"}
        violations = validate(document, resolved_profile)
        errors = [
            v
            for v in violations
            if v.severity == "error" and v.check_code not in _IGNORED_BY_BUILDER
        ]
        if errors:
            codes = sorted({v.check_code for v in errors})
            raise ValueError("Документ не проходит валидацию: " + ", ".join(codes))

        export_docx(document, resolved_profile, Path(path))


def work(
    title: str,
    author: str = "",
    year: int | None = None,
    work_type: WorkType = "coursework",
    profile_id: str = "gost-7.32-2017",
    *,
    supervisor: str = "",
    organization: str = "",
) -> WorkBuilder:
    """Фабричная функция для начала цепочки `work(...).section(...)...`.

    Пример:
        from gostforge.builder import work
        doc = work("Курсовая", author="Иванов", year=2026).section("Введение").build()
    """
    return WorkBuilder(
        title=title,
        author=author,
        year=year,
        work_type=work_type,
        profile_id=profile_id,
        supervisor=supervisor,
        organization=organization,
    )


# --- Хелперы -----------------------------------------------------------------


_DEFAULT_MARGINS_MM = {"top": 20.0, "right": 15.0, "bottom": 20.0, "left": 30.0}
_DEFAULT_START_VALUE = 3

# Заголовок приложения по ГОСТ Р 2.105/7.32: «Приложение А», «Приложение Б», ...
# Кириллические буквы кроме «Ё», «З», «Й», «О», «Ч», «Ъ», «Ы», «Ь» — но в
# простой эвристике принимаем любые А-Я. Захватываем сам буквенный
# идентификатор.
_APPENDIX_HEADING_RE = re.compile(r"^\s*приложение\s+([А-Я])\b", re.IGNORECASE)


def _parse_appendix_letter(heading: str) -> str | None:
    """Если заголовок — «Приложение X[. ...]», вернуть букву X в верхнем регистре.

    Иначе None — это обычная глава, не приложение.
    """
    match = _APPENDIX_HEADING_RE.match(heading)
    if not match:
        return None
    return match.group(1).upper()


def _resolve_caption_settings_from_profile(
    profile_id: str,
) -> tuple[
    Literal["continuous", "by_chapter"],
    Literal["continuous", "by_chapter"],
    str,
    str,
]:
    """Прочитать схемы нумерации и форматы подписей из профиля.

    Возвращает кортеж (figure_mode, table_mode, figure_caption_format,
    table_caption_format). При ошибке загрузки — («continuous»,
    «continuous», «Рисунок {num} — {title}», «Таблица {num} — {title}»),
    т.е. поведение до этой сессии остаётся обратносовместимым.
    """
    default_fig_fmt = "Рисунок {num} — {title}"
    default_tbl_fmt = "Таблица {num} — {title}"
    try:
        from gostforge.profile import load_profile

        profile = load_profile(profile_id)
    except Exception:
        return "continuous", "continuous", default_fig_fmt, default_tbl_fmt
    fig_fmt = profile.styles.figure.caption.format or default_fig_fmt
    tbl_fmt = profile.styles.table.caption.format or default_tbl_fmt
    return (
        profile.styles.figure.numbering,
        profile.styles.table.numbering,
        fig_fmt,
        tbl_fmt,
    )


def _resolve_numbering_modes_from_profile(
    profile_id: str,
) -> tuple[Literal["continuous", "by_chapter"], Literal["continuous", "by_chapter"]]:
    """Прочитать только схемы нумерации (back-compat-обёртка над
    `_resolve_caption_settings_from_profile`)."""
    fig, tbl, _, _ = _resolve_caption_settings_from_profile(profile_id)
    return fig, tbl


def _resolve_page_params_from_profile(
    profile_id: str,
) -> tuple[dict[str, float], int]:
    """Извлечь поля страницы и start_value нумерации из профиля.

    Если профиль не зарегистрирован или не удалось загрузить — возвращаем
    дефолты ГОСТ 7.32-2017. Профиль может прийти с любого окружения
    (тесты, пользовательский YAML), поэтому делаем мягко через
    try/except — builder не должен падать на этапе build() из-за
    конфига профиля.
    """
    try:
        from gostforge.profile import load_profile

        profile = load_profile(profile_id)
    except Exception:
        return dict(_DEFAULT_MARGINS_MM), _DEFAULT_START_VALUE

    margins = dict(_DEFAULT_MARGINS_MM)
    margins.update({k: float(v) for k, v in profile.styles.page.margins_mm.items()})

    start_value = _DEFAULT_START_VALUE
    f06 = profile.checks.get("F.06")
    if f06 and f06.params.get("start_value") is not None:
        with contextlib.suppress(TypeError, ValueError):
            start_value = int(f06.params["start_value"])

    return margins, start_value


def _find_first_paragraph(section: LogicalSection) -> Paragraph | None:
    """Найти первый Paragraph в дереве раздела (depth-first)."""
    for child in section.children:
        if isinstance(child, Paragraph):
            return child
        if isinstance(child, LogicalSection):
            found = _find_first_paragraph(child)
            if found is not None:
                return found
        # Table/Figure/Formula/ListBlock — не пара­графы, пропускаем.
    return None


def _section_paragraphs(section: LogicalSection) -> list[Paragraph]:
    """Все Paragraph-ы первого уровня внутри раздела (без рекурсии в подразделы)."""
    return [child for child in section.children if isinstance(child, Paragraph)]


def _extract_bibliography(document: Document) -> None:
    """Пост-обработка: формирование `Document.bibliography` из секции «Список...».

    Симметрично парсеру: ищет в `page_sections` логический раздел, чей заголовок
    подходит под алиасы, и превращает его параграфы в `BibliographyEntry`.
    """
    for page_section in document.page_sections:
        for child in page_section.content:
            if not isinstance(child, LogicalSection):
                continue
            heading = _heading_text(child).strip().lower()
            if heading not in _BIBLIOGRAPHY_HEADINGS:
                continue
            for para in _section_paragraphs(child):
                raw_text = _paragraph_text(para)
                if not raw_text.strip():
                    continue
                entry_type = _entry_type_from_id(para.id)
                document.bibliography.append(
                    BibliographyEntry(
                        id=para.id,
                        type=entry_type,
                        fields={"raw": raw_text},
                    )
                )


def _paragraph_text(para: Paragraph) -> str:
    """Склеить inline-содержимое параграфа в строку."""
    parts: list[str] = []
    for el in para.content:
        if isinstance(el, TextRun):
            parts.append(el.text)
    return "".join(parts)


_ALLOWED_ENTRY_TYPES: frozenset[str] = frozenset(
    {"book", "article", "web", "standard", "thesis", "conference", "law"}
)


def _entry_type_from_id(
    para_id: str,
) -> Literal["book", "article", "web", "standard", "thesis", "conference", "law"]:
    """Восстановить тип записи из id формата `ref:<type>-N`. По умолчанию — book."""
    if para_id.startswith("ref:"):
        rest = para_id[len("ref:") :]
        type_part = rest.split("-", 1)[0]
        if type_part in _ALLOWED_ENTRY_TYPES:
            return cast(
                "Literal['book', 'article', 'web', 'standard', 'thesis', 'conference', 'law']",
                type_part,
            )
    return "book"
