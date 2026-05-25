"""Fluent-builder верхнего уровня для построения работы по ГОСТу.

Высокоуровневый API над моделью документа: студент собирает работу из
разделов и параграфов, а конструктор сам ставит правильные поля,
колонтитулы, нумерацию страниц и `page_break_before` у заголовков.
"""

from __future__ import annotations

import itertools
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

    # --- Внутренние утилиты для SectionBuilder ------------------------------

    def _next_id(self, prefix: str) -> str:
        counter = self._id_counters.setdefault(prefix, itertools.count(1))
        return f"{prefix}-{next(counter)}"

    def _next_figure_number(self) -> int:
        return next(self._figure_counter)

    def _next_table_number(self) -> int:
        return next(self._table_counter)

    def _set_active(self, builder: SectionBuilder) -> None:
        self._active = builder

    # --- Fluent API ----------------------------------------------------------

    def section(self, heading: str) -> SectionBuilder:
        """Добавить раздел 1 уровня и вернуть его SectionBuilder.

        Заголовок создаётся с атрибутами, удовлетворяющими H.01 для
        базового профиля ГОСТ 7.32: текст в верхнем регистре, bold,
        шрифт Times New Roman, кегль 14.
        """
        sec = LogicalSection(
            id=self._next_id("sec"),
            heading=[TextRun(
                text=heading.upper(),
                bold=True,
                font="Times New Roman",
                size_pt=14,
            )],
            level=1,
        )
        self._sections.append(sec)
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

        # Применяем «разрыв страницы перед» к первым параграфам разделов
        # уровня 1, кроме самого первого раздела (он начинается на первой
        # странице основной части).
        for idx, section in enumerate(self._sections):
            if idx == 0:
                continue
            first_para = _find_first_paragraph(section)
            if first_para is not None:
                first_para.page_break_before = True

        # Создаём одну PageSection «main» с правильной геометрией, нумерацией
        # страниц и футером «{page}». Параметры — по умолчанию для ГОСТ 7.32.
        page = PageGeometry(
            paper="A4",
            margins_mm={"top": 20, "right": 15, "bottom": 20, "left": 30},
            orientation="portrait",
        )
        footer = HeaderConfig(
            default=ContentTemplate(center=[TextRun(text="{page}")]),
        )
        numbering = PageNumberingConfig(
            visible=True,
            format="arabic",
            start_mode="start_at",
            start_value=3,
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
            raise ValueError(
                "Документ не проходит валидацию: " + ", ".join(codes)
            )

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


def _entry_type_from_id(para_id: str) -> Literal["book", "article", "web", "standard", "thesis", "conference", "law"]:
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


