# ruff: noqa: RUF002

"""Fluent-builder для одного логического раздела."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gostforge.model import (
    Document,
    Figure,
    Formula,
    InlineElement,
    ListBlock,
    LogicalSection,
    Paragraph,
    Table,
    TableOfContents,
    TextRun,
)

if TYPE_CHECKING:
    from gostforge.profile import Profile

    from .work_builder import WorkBuilder


# Алиасы заголовков раздела «Список использованных источников».
_BIBLIOGRAPHY_HEADINGS: frozenset[str] = frozenset(
    {
        "список использованных источников",
        "список литературы",
        "библиографический список",
        "список источников",
    }
)


class SectionBuilder:
    """Fluent API для одного раздела (уровень 1 или 2).

    Хранит ссылку на корневой `WorkBuilder` (для возврата к нему через `.section`)
    и на текущий `LogicalSection`, в который пишет дочерние элементы.
    После любого add-метода возвращает `self` — чтобы цепочка не прерывалась.
    """

    def __init__(self, root: WorkBuilder, section: LogicalSection) -> None:
        self._root = root
        self._section = section

    # --- Внутренний доступ ---------------------------------------------------

    @property
    def current_section(self) -> LogicalSection:
        """Текущий логический раздел (только для интроспекции в тестах)."""
        return self._section

    @property
    def root(self) -> WorkBuilder:
        """Корневой WorkBuilder (для интроспекции и переключения раздела)."""
        return self._root

    # --- Контент -------------------------------------------------------------

    def paragraph(self, text: str, *, bold: bool = False, italic: bool = False) -> SectionBuilder:
        """Добавить параграф в текущий раздел.

        Высокоуровневая обёртка для случая «один абзац = одна строка с
        опциональным сквозным форматированием». Для inline-формул,
        перекрёстных ссылок и mixed-форматирования используйте
        :meth:`rich_paragraph`.
        """
        return self.rich_paragraph([TextRun(text=text, bold=bold, italic=italic)])

    def rich_paragraph(self, elements: list[InlineElement]) -> SectionBuilder:
        """Добавить параграф с готовым набором inline-элементов.

        Низкоуровневая альтернатива :meth:`paragraph` для случаев, когда
        нужны inline-формулы, перекрёстные ссылки, цитаты или смешанное
        форматирование внутри одного абзаца. Принимает любую комбинацию
        TextRun / CrossRef / InlineFormula / Citation в нужном порядке.
        """
        para = Paragraph(
            id=self._root._next_id("p"),
            content=list(elements),
        )
        self._section.children.append(para)
        return self

    def figure(self, image_path: str, caption: str) -> SectionBuilder:
        """Добавить рисунок с подписью (нумерация проставится автоматически).

        Если `image_path` указывает на существующий файл, экспортёр вставит
        реальное изображение; иначе — placeholder-параграф `[Рисунок: id]`.
        """
        number = self._root._next_figure_number()
        fig = Figure(
            id=self._root._next_id("fig"),
            image_path=image_path,
            caption=[TextRun(text=f"Рисунок {number} — {caption}")],
            number=number,
        )
        self._section.children.append(fig)
        return self

    # `image` — синоним `figure` с расширенной сигнатурой; на Фазе 1 параметр
    # width_cm пока не пробрасывается в модель (не хранится), но принимается
    # для совместимости с будущей версией API.
    def image(
        self,
        image_path: str,
        caption: str,
        *,
        width_cm: float | None = None,  # noqa: ARG002
    ) -> SectionBuilder:
        """Добавить рисунок (синоним `figure` с дополнительным параметром width_cm)."""
        return self.figure(image_path, caption)

    def list(self, items: list[str], *, ordered: bool = False) -> SectionBuilder:
        """Добавить маркированный или нумерованный список.

        Экспортёр использует Word-стили `List Number` / `List Bullet`,
        если они есть в шаблоне, иначе — fallback на префиксы «1. » / «• ».
        """
        block = ListBlock(
            id=self._root._next_id("list"),
            ordered=ordered,
            items=[[TextRun(text=item)] for item in items],
        )
        self._section.children.append(block)
        return self

    def table_of_contents(
        self,
        *,
        min_level: int = 1,
        max_level: int = 3,
    ) -> SectionBuilder:
        """Вставить автоматическое оглавление документа.

        Реализуется через Word TOC-field. При открытии .docx Word
        предложит обновить оглавление (или F9), и сформирует список
        заголовков с номерами страниц.

        Параметры:
        * ``min_level`` / ``max_level`` — диапазон уровней заголовков
          в оглавлении (default 1-3 — главы, подразделы, пункты).

        Пример::

            work("Курсовая", year=2026) \\
                .section("Содержание").table_of_contents() \\
                .section("Введение").paragraph("...")
        """
        block = TableOfContents(
            id=self._root._next_id("toc"),
            min_level=min_level,
            max_level=max_level,
        )
        self._section.children.append(block)
        return self

    def formula(self, latex: str, *, numbered: bool = True) -> SectionBuilder:
        """Добавить формулу. Если numbered=True, нумерация автоматическая.

        На Фазе 1 экспортёр формул не пишет в OOXML, поэтому в результирующем
        .docx формула пока не появится. Парсер уже умеет читать `<m:oMath>`,
        так что round-trip из существующих документов работает.
        """
        number = self._root._next_formula_number() if numbered else None
        formula = Formula(
            id=self._root._next_id("formula"),
            latex=latex,
            number=number,
        )
        self._section.children.append(formula)
        return self

    def table(
        self,
        headers: list[str],
        rows: list[list[str]],
        caption: str,
    ) -> SectionBuilder:
        """Добавить таблицу с автонумерованной подписью."""
        number = self._root._next_table_number()
        tbl = Table(
            id=self._root._next_id("tbl"),
            caption=[TextRun(text=f"Таблица {number} — {caption}")],
            headers=[[TextRun(text=h)] for h in headers],
            rows=[[[TextRun(text=cell)] for cell in row] for row in rows],
            number=number,
        )
        self._section.children.append(tbl)
        return self

    def reference(self, entry_raw: str, type: str = "book") -> SectionBuilder:
        """Добавить запись списка литературы.

        Разрешено только внутри раздела «Список использованных источников»
        (или его синонимов). В саму модель записывается как обычный
        `Paragraph` с raw-текстом; `Document.bibliography` затем заполняется
        в `WorkBuilder.build()` пост-обработкой (симметрично парсеру).
        """
        heading_text = _heading_text(self._section).strip().lower()
        if heading_text not in _BIBLIOGRAPHY_HEADINGS:
            raise ValueError(
                "reference() допустим только внутри раздела «Список использованных "
                f"источников»; текущий заголовок: «{_heading_text(self._section)}»"
            )
        # Сохраняем тип записи как «namespaced» id, чтобы build() умел
        # восстанавливать его при формировании BibliographyEntry.
        para = Paragraph(
            id=self._root._next_id(f"ref:{type}"),
            content=[TextRun(text=entry_raw)],
        )
        self._section.children.append(para)
        return self

    # --- Переключение раздела ------------------------------------------------

    def subsection(self, heading: str) -> SectionBuilder:
        """Создать подраздел (level=2) внутри текущего раздела level=1.

        Если текущий раздел сам уже level>=2 — подраздел будет level+1.
        """
        new_level = self._section.level + 1
        sub = LogicalSection(
            id=self._root._next_id("sec"),
            heading=[TextRun(text=heading)],
            level=new_level,
        )
        self._section.children.append(sub)
        new_builder = SectionBuilder(self._root, sub)
        # Регистрируем активный «фокус» подраздела в корне, чтобы будущие
        # вызовы `.paragraph()` через корневой fluent API писали туда же.
        self._root._set_active(new_builder)
        return new_builder

    def section(self, heading: str) -> SectionBuilder:
        """Закрыть текущий раздел и открыть новый раздел уровня 1."""
        return self._root.section(heading)

    # --- Нормоконтроль раздела ----------------------------------------------

    def skip_checks(self, *codes: str) -> SectionBuilder:
        """Отключить указанные проверки для этого раздела.

        Пример::

            (work("Курсовая", year=2026)
                .section("Титульный лист")
                    .paragraph("...")
                    .skip_checks("H.01", "T.04", "T.05")
                .section("Введение")
                    .paragraph("..."))

        Принятые коды добавляются к ``LogicalSection.disabled_checks``,
        дубликаты игнорируются. Валидатор не сообщит о нарушениях с
        этими кодами для содержимого раздела (и его дочерних узлов).
        """
        existing = set(self._section.disabled_checks)
        for code in codes:
            existing.add(code)
        self._section.disabled_checks = sorted(existing)
        return self

    def skip_all_checks(self) -> SectionBuilder:
        """Отключить ВСЕ проверки для этого раздела.

        Спецзначение ``"*"`` в ``disabled_checks``. Удобно для титульного
        листа, реферата и приложений, которые оформляются по своим
        правилам (или по шаблону кафедры), не по ГОСТу.
        """
        self._section.disabled_checks = ["*"]
        return self

    # --- Терминальные операции ----------------------------------------------

    def build(self) -> Document:
        """Делегирует корневому WorkBuilder."""
        return self._root.build()

    def save(self, path: str | Path, profile: str | Profile | None = None) -> None:
        """Делегирует корневому WorkBuilder."""
        self._root.save(path, profile)


def _heading_text(section: LogicalSection) -> str:
    """Склеить заголовок раздела в строку (для сравнения с алиасами)."""
    parts: list[str] = []
    for el in section.heading:
        if isinstance(el, TextRun):
            parts.append(el.text)
    return "".join(parts)
