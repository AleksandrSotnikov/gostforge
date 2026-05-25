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
│     ├─ LogicalSection               # раздел: heading, level, children
│     ├─ Paragraph                    # style_name, alignment, line_spacing,
│     │                                # first_line_indent_cm, page_break_before,
│     │                                # content: (TextRun | CrossRef)[]
│     ├─ Table                        # caption, headers, rows
│     ├─ Figure                       # image_path, caption
│     ├─ Formula                      # latex (Фаза 3)
│     └─ ListBlock / CodeBlock        # роадмап
├─ bibliography: BibliographyEntry[] # id, type, fields
└─ abbreviations: dict[str, str]
```

**Ключевое разделение:** `PageSection` ≠ `LogicalSection`.
PageSection — вёрстка (поля, колонтитулы); LogicalSection — содержание
(введение, глава 1). Одна PageSection обычно содержит много
LogicalSection. См. [page-sections.md](page-sections.md).

`SCHEMA_VERSION` фиксирует версию модели — при изменении нужна миграция.

### Profile (`src/gostforge/profile/`)

YAML-файл, объединяющий три аспекта стандарта:

1. **Стили** (`styles.page`, `styles.body`, `styles.extra.heading_1`...) —
   для экспортёра.
2. **Шаблон секций** (`sections_template`) — какие PageSection создавать
   по умолчанию, с какими колонтитулами и нумерацией.
3. **Правила проверок** (`checks.X.NN: {enabled, params}`) — реестр и
   параметры для валидатора.

**Наследование через deep-merge:** `extends: gost-7.32-2017` подгружает
родителя и сливает по ключам (любой словарный уровень). Ребёнок
переопределяет только то, что отличается.

Загрузка: `gostforge.profile.load_profile(id)` ищет в `profiles/`
репозитория и в `~/.gostforge/profiles/`.

Подробнее: [profiles.md](profiles.md) — пошаговый гайд по созданию
профиля кафедры.

### Parser (`src/gostforge/parser/`)

Преобразует `.docx → Document`. python-docx для базы, lxml — для
нестандартных случаев (поля PAGE в колонтитулах, w:pgNumType,
w:pageBreakBefore через цепочку стилей).

Текущее покрытие:
- Поля страницы, формат бумаги (A4/A3/A5/Letter/Legal), ориентация.
- Метаданные из `docProps`.
- Параграфы со стилями и runs (font, size, bold, italic).
- Заголовки `Heading 1..4` → LogicalSection с вложением.
- Таблицы и рисунки со склейкой подписей (Caption-стиль или regex).
- Header/footer с полем PAGE (`<w:fldSimple>` и `fldChar+instrText`).
- `<w:pgNumType>` с `w:start` и `w:fmt`.
- `<w:pageBreakBefore>` (включая наследование от Word-стиля).
- Раздел «Список использованных источников» → `BibliographyEntry`.

Не покрыто: формулы (OMML), перекрёстные ссылки, реальные растровые
изображения (только метаданные `<w:drawing>`).

### Exporter (`src/gostforge/exporter/`)

Преобразует `Document → .docx`. python-docx + lxml для записи
sectPr/footer/pgNumType. Round-trip parse → export → parse сохраняет
все поддерживаемые атрибуты.

Покрытие зеркалит парсер: поля, формат бумаги, ориентация, стиль Normal,
параграфы (включая alignment / line_spacing / first_line_indent / break),
заголовки, таблицы с подписями, рисунки как placeholder-параграфы (на
Фазе 1 без реальных изображений), footer с полем PAGE, pgNumType.

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

### CLI (`src/gostforge/cli.py`)

```bash
gostforge check work.docx --profile gost-7.32-2017 [--report file.xlsx|.md] [--quiet]
gostforge fix work.docx -o fixed.docx [--only T.08] [--dry-run]
gostforge stats work.docx
gostforge new out.docx --template coursework --title "..." --year 2026
gostforge profiles list|show <id>
gostforge checks
gostforge ui
```

Exit codes: `0` — нарушений нет; `1` — найдены error; `2` — ошибка
загрузки профиля.

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
