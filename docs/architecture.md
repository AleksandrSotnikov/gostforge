# Архитектура

## Обзор

`gostforge` — двухрежимная система с общим ядром:

- **Режим «Нормоконтроль»** для проверяющих: автоматическая проверка
  чужих `.docx` против профиля ГОСТ или методички кафедры. Реализовано.
- **Режим «Конструктор»** для студентов: программный API (а позже —
  визуальный редактор) для написания работ с нуля, с гарантией
  соответствия выбранному профилю. API стартует в Фазе 1, GUI — Фаза 2.

Оба режима работают через единые компоненты: `Model`, `Profile`,
`Parser`, `Exporter`, `Validator`, `Fixer`.

## Компоненты (текущая реализация)

### Model (`src/gostforge/model/`)

Внутреннее представление документа, **независимое** от Word/OOXML —
никаких ссылок на python-docx/lxml внутри. Dataclass-ы:

```
Document
├─ metadata: DocumentMetadata        # title, author, supervisor, year, work_type
├─ page_sections: PageSection[]      # секции вёрстки
│  ├─ id, name, type (title/frontmatter/main/appendix)
│  ├─ page: PageGeometry             # paper (A4..), orientation, margins_mm
│  ├─ header / footer: HeaderConfig  # ContentTemplate(left/center/right)
│  ├─ page_numbering: PageNumberingConfig
│  │  └─ visible, format (arabic/roman/letter), start_mode, start_value
│  └─ content: (LogicalSection | Block)[]
│     ├─ LogicalSection               # раздел: heading, level, children,
│     │                                # disabled_checks (skip-checks для секции)
│     ├─ Paragraph                    # style_name, alignment, line_spacing,
│     │                                # first_line_indent_cm, page_break_before,
│     │                                # space_before_pt, space_after_pt,
│     │                                # content: InlineElement[]
│     ├─ Table                        # caption, headers, rows
│     ├─ Figure                       # image_path, caption, dpi, alignment
│     ├─ Formula                      # latex (блочная, через m:oMathPara)
│     └─ ListBlock                    # ordered, items, item_levels
├─ bibliography: BibliographyEntry[] # id, type, fields
├─ comments: Comment[]                # рецензент-комментарии из word/comments.xml
└─ abbreviations: dict[str, str]
```

**Новое в актуальной версии:**

* `LogicalSection.disabled_checks: list[str]` — список кодов проверок,
  не применяемых к разделу (или `["*"]` чтобы отключить все). Фича
  конструктора — для титульного, реферата, приложений.
* `Paragraph.space_before_pt` / `space_after_pt: float | None` —
  межабзацные интервалы. Используется проверкой T.14 и автофиксером.
* `ListBlock.item_levels: list[int]` — уровень вложенности каждого
  элемента (0..N) для multilevel-numbering. Пустой = плоский (default).
* `Comment` (новый dataclass): id, author, date, text, section_id —
  комментарии рецензента, извлечённые парсером из `word/comments.xml`.

**InlineElement** (`Paragraph.content` и `Caption`) — union из 4 типов
(Фаза 2.5, `SCHEMA_VERSION = 0.3.0`):

| Тип | Поля | OOXML соответствие |
| --- | --- | --- |
| `TextRun` | text + bold/italic/underline/sup/sub/font/size/color_hex | `<w:r><w:rPr>…</w:rPr><w:t>…</w:t></w:r>` |
| `CrossRef` | target_id, display_template, prefix | `<w:fldSimple w:instr=" REF target_id \h "/>` (опц. предшествующий run для prefix) |
| `InlineFormula` | latex, id | `<w:r><m:oMath>…</m:oMath></w:r>` (inline OMML внутри run) |
| `Citation` | source_id, pages, template | текстовый run «[N]» / «[N, с. P]» (N = индекс в bibliography) |

Inline-формулы (`InlineFormula`) отличаются от блочных (`Formula`):
последние идут отдельным абзацем через `<m:oMathPara>`, первые — в
потоке inline-контента параграфа.

**Ключевое разделение:** `PageSection` ≠ `LogicalSection`.
PageSection — вёрстка (поля, колонтитулы); LogicalSection — содержание
(введение, глава 1). Одна PageSection обычно содержит много
LogicalSection. См. [page-sections.md](page-sections.md).

`SCHEMA_VERSION` фиксирует версию модели — при изменении нужна миграция.

### Profile (`src/gostforge/profile/`)

YAML-файл, объединяющий три аспекта стандарта:

1. **Стили** (`styles.page`, `styles.body`, `styles.heading_1..4`,
   `styles.figure`, `styles.table`, `styles.lists`) — для экспортёра.
   Типизированы как Pydantic-классы:
   * `BodyTextProfile`: font, size_pt, line_spacing,
     first_line_indent_cm, alignment, hyphenation,
     **space_before_pt**, **space_after_pt** (0 по ГОСТу).
   * `HeadingStyleProfile`: font, size_pt, bold, italic, uppercase,
     **color** (auto/hex), alignment, spacing_before/after_pt,
     page_break_before, keep_with_next.
   * `CaptionStyleProfile` для рисунков и таблиц (alignment,
     position, format).
   * `TableStyleProfile`: border_style, border_size, border_color,
     header_bold + nested caption.
   * `FigureStyleProfile`: alignment (center) + nested caption.
   * `ListStyleProfile`: bullet_char, ordered_format,
     left_indent_cm, hanging_indent_cm.
2. **Шаблон секций** (`sections_template`) — какие PageSection создавать
   по умолчанию, с какими колонтитулами и нумерацией.
3. **Правила проверок** (`checks.X.NN: {enabled, params}`) — реестр и
   параметры для валидатора.

**Наследование через deep-merge:** `extends: gost-7.32-2017` подгружает
родителя и сливает по ключам (любой словарный уровень). Ребёнок
переопределяет только то, что отличается.

Загрузка: `gostforge.profile.load_profile(id)` ищет в `profiles/`
репозитория и в `~/.gostforge/profiles/`.

**Style overrides в UI:** в Streamlit-конструкторе sidebar содержит
секцию «Настройки стилей» — переопределения профиля для текущего
документа без правки YAML. Хранятся в `state["style_overrides"]` и
применяются через `_apply_style_overrides(profile, overrides)` перед
экспортом. Поддерживаются: поля страницы, шрифт основного текста,
кегль, межстрочный, отступ красной строки, **интервалы между абзацами**,
ВЕРХНИЙ-регистр / цвет / spacing для heading_1, символ маркера и
шаблон нумерации списков, стиль рамок таблиц.

Подробнее: [profiles.md](profiles.md) — пошаговый гайд по созданию
профиля кафедры.

### Parser (`src/gostforge/parser/`)

Преобразует `.docx → Document`. python-docx для базы, lxml — для
нестандартных случаев (поля PAGE в колонтитулах, w:pgNumType,
w:pageBreakBefore через цепочку стилей).

Текущее покрытие:
- Поля страницы, формат бумаги (A4/A3/A5/Letter/Legal), ориентация.
- Метаданные из `docProps` (включая **year** из `core.created`).
- Параграфы со стилями и runs (font, size, bold, italic, underline,
  color, space_before/after).
- **Style-cascade**: для run-ов без явных rPr-атрибутов наследует
  font/size/bold/italic/color от стиля параграфа (Heading{N}, Normal)
  и от его linked character-стиля (Heading1Char и т. д.). Без этого
  H.01/H.02 были бы «слепы» к стилевому форматированию.
- Заголовки `Heading 1..4` → LogicalSection с вложением.
- Реконструкция иерархии разделов из плоского списка по level
  (`_reconstruct_section_hierarchy`).
- Таблицы и рисунки со склейкой подписей.
- Header/footer с полем PAGE.
- `<w:pgNumType>` с `w:start` и `w:fmt`.
- `<w:pageBreakBefore>` (включая наследование).
- Списки: `<w:numPr>` → `ListBlock` с правильным `ordered`-флагом
  (через `numFmt` в numbering.xml), группировка по `numId`,
  fallback на эвристику текстовых маркеров для документов
  без numbering.xml (`_group_text_marker_lists`).
- Раздел «Список использованных источников» → `BibliographyEntry`.
- **Комментарии рецензента** из `word/comments.xml` (id, author,
  date, text) — в `Document.comments`.
- Inline-formula (OMML внутри `<w:r>`), CrossRef
  (`<w:fldSimple w:instr=" REF ... "/>`), Citation.

### Exporter (`src/gostforge/exporter/`)

Преобразует `Document → .docx`. python-docx + lxml для записи
sectPr/footer/pgNumType/numbering.xml. Round-trip parse → export →
parse сохраняет все поддерживаемые атрибуты.

Покрытие зеркалит парсер. Дополнительно:
- **`_apply_heading_styles`** переписывает стили Heading 1..4 из
  python-docx-дефолтов (синие Cambria) под профиль: явный
  Times New Roman через `_clear_theme_fonts`, `color=auto`,
  spacing_before/after из профиля, page_break_before, keep_with_next.
  Также через `_sync_linked_char_style` — соответствующие
  HeadingNChar character-стили (иначе синий цвет лезет через них).
- **`_apply_normal_style`** ставит `space_before/after = 0` явно
  (по дефолту Word наследует 10 pt → между абзацами вылезает
  лишнее белое поле).
- **`_apply_caption_style`** — выравнивание подписи рисунка (центр)
  vs. таблицы (слева) согласно ГОСТу.
- **`_apply_table_borders`** — все 6 сторон `<w:tblBorders>`
  (top/left/bottom/right/insideH/insideV) — Word-дефолт без
  рамок не годится.
- **`_ensure_list_num_in_numbering`** — настоящие numPr-списки
  через `word/numbering.xml`: добавляет abstractNum + num, с
  multiLevelType=singleLevel (для плоских) или multilevel (если
  `item_levels` содержит >0). suff=space между маркером и текстом.
- **`_sync_page_section_with_profile`** — на этапе экспорта согласует
  margins_mm и `F.06.start_value` с активным профилем (закрывает
  баг, когда builder.build() ставит дефолты, а export через ESCD
  даёт F.06).
- Год работы пишется в `core.created` (1 января указанного года),
  чтобы парсер прочитал его обратно при import-docx.

### Validator (`src/gostforge/validator/`)

Прогоняет Document через включённые в профиле проверки.

```
@register("F.01")
def check_margins(doc: Document, profile: Profile) -> list[Violation]:
    ...
```

`Violation`: `check_code`, `severity` (error/warning/info), `message`,
`location` (путь в модели), `suggestion`, `details` (для отчётов).

Категории: F (страница), T (текст), S (структура), H (заголовки),
I (рисунки), B (таблицы), R (литература), плюс зарезервированы C, A,
P, K, V, X. Каталог со статусом: [checks-catalog.md](checks-catalog.md).
Команда `gostforge checks` показывает актуально реализованные коды.

### Fixer (`src/gostforge/fixer/`)

Симметричен валидатору, но **мутирует Document** — применяет безопасные
правки и возвращает `list[FixApplied]`. Безопасные = не меняют смысл
текста.

```
@register("T.08")
def fix_double_spaces(doc: Document, profile: Profile) -> list[FixApplied]:
    ...
```

Текущие фиксеры: T.08, T.09, T.10, T.11, H.03, H.08.

Команда `gostforge fix work.docx -o fixed.docx` парсит → фиксит →
экспортирует. Поддерживает `--only` для выборки кодов и `--dry-run`.

### Builder (`src/gostforge/builder/`) — в активной разработке

Конструктор работ: fluent API для программного построения Document.

```python
from gostforge.builder import work

(
    work("Курсовая", author="Иван Иванов", year=2026)
    .section("Введение").paragraph("Актуальность ...")
    .section("Заключение").paragraph("Выводы ...")
    .section("Список использованных источников")
        .reference("Иванов И. И. ... — М. : Наука, 2023. — 320 с.")
    .save("coursework.docx")
)
```

Builder автоматически расставляет `page_break_before` у разделов уровня
1, footer с PAGE, `pgNumType.start = 3` — собранный документ проходит
проверки без нарушений из коробки.

Шаблоны: `coursework_template`, `bachelor_thesis_template`,
`research_report_template`. CLI-команда: `gostforge new my-coursework.docx
--template coursework --title "..."`.

### PDF-Exporter (`src/gostforge/pdf_exporter.py`)

Тонкая обёртка над LibreOffice headless: `convert_to_pdf(input, output)`
вызывает `soffice --headless --convert-to pdf` во временной директории
и переносит результат в указанный путь. Если LibreOffice не установлен —
поднимается `LibreOfficeNotFoundError` с подсказкой по установке.
Изолирован от парсера и экспортёра — это отдельный артефакт «финальной»
сборки документа после автофиксов.

### PDF-Importer (`src/gostforge/pdf_importer.py`)

`import_pdf_to_state(pdf_path)` извлекает структуру (заголовки +
параграфы) из PDF через pdfplumber и строит state-словарь
конструктора. Заголовки распознаются эвристикой: структурные разделы
(«Введение», «Заключение», «Список…»), нумерация «1.1 X», ВЕРХНИЙ
регистр. Библиография складывается в `references`; внутри неё
нумерованные строки («1. Иванов…») остаются ссылками, а не считаются
заголовками. Форматирование не переносится — структура довёрстывается
в UI по ГОСТу. pdfplumber — опциональный extra `[import-formats]`; без
него поднимается `PdfImportError`.

### CLI (`src/gostforge/cli.py`)

```bash
gostforge check work.docx --profile gost-7.32-2017 [--report file.xlsx|.md] [--quiet]
gostforge fix work.docx -o fixed.docx [--only T.08] [--dry-run]
gostforge stats work.docx
gostforge new out.docx --template coursework --title "..." --year 2026
gostforge pdf work.docx -o work.pdf [--timeout 60]
gostforge profiles list|show <id>
gostforge checks
gostforge ui
```

Exit codes: `0` — нарушений нет; `1` — найдены error; `2` — ошибка
загрузки профиля; для `pdf` дополнительно: `3` — LibreOffice не найден,
`4` — таймаут, `5` — LibreOffice вернул ошибку. Для `import-pdf`: `3` —
не установлен pdfplumber (extra `[import-formats]`).

### Web (`src/gostforge/web/`)

Streamlit-приложение. Drag-and-drop загрузка `.docx`, выбор профиля в
sidebar, три вкладки на каждый файл:
- **Проверка** — таблица нарушений.
- **Статистика** — метрики через `gostforge.stats.compute_stats`.
- **Автоисправление** — кнопка скачивания исправленного `.docx`.

Плюс кнопки скачивания Markdown / Excel-отчётов внизу. Запуск:
`gostforge ui` (требует extra `gostforge[ui]`).

## Потоки данных

### Нормоконтроль (готов)
```
.docx → Parser → Document ─┬─→ Validator + Profile ─→ list[Violation] ─→ CLI/UI/Report
                            └─→ Stats             ─→ DocumentStats
```

### Автоисправление (готов)
```
.docx → Parser → Document ─→ Fixer + Profile (мутирует) ─→ Exporter + Profile ─→ fixed.docx
                                              ↓
                                     list[FixApplied] ─→ CLI/UI
```

### Конструктор (в разработке)
```
WorkBuilder.section()/paragraph()/... → Document ─→ Exporter + Profile ─→ .docx
```

### Импорт (Фаза 3+)
```
Чужой .docx → Parser → Document → JSON-файл проекта → редактирование в Builder
```

## Расширяемость

- **Новые проверки** — функция с `@register("X.NN")` в любом модуле
  `validator/checks/*.py` плюс запись в профиле. Без изменения движка.
- **Новые фиксеры** — то же самое в `fixer/fixers/*.py`.
- **Новые форматы отчётов** — функция `_write_X_report` в `cli.py` +
  ветка в `_write_report` (диспетчер по расширению файла).
- **Новые профили** — YAML в `profiles/` или `~/.gostforge/profiles/`,
  через `extends:` от родителя.

## Что в roadmap

- Парсер: формулы (OMML), реальные изображения, перекрёстные ссылки.
- Builder: визуальный редактор (PyQt/Web) поверх API.
- Аннотация `.docx` комментариями Word для проверяющих.
- REST API (FastAPI) для интеграций с LMS.
- SQLite-хранилище для истории прогонов и архива работ.
- Плагинная система (`~/.gostforge/plugins/`).
- Маркетплейс профилей кафедр.

См. [roadmap.md](roadmap.md) для детального плана фаз.
