# gostforge

**Конструктор и нормоконтролёр документов по ГОСТу.**

Инструмент для двух сценариев:

1. **Нормоконтроль** — автоматическая проверка чужих `.docx`
   (курсовых, дипломных, ВКР, отчётов о НИР) на соответствие
   ГОСТ 7.32-2017, ГОСТ Р 2.105-2019, ГОСТ Р 7.0.100-2018 и/или
   методичкам кафедр. Результат — отчёт + аннотированный `.docx`
   с комментариями Word ровно в проблемных местах.
2. **Конструктор** — структурный редактор для написания работ с
   нуля. Студент собирает документ из блоков (раздел, абзац,
   таблица, рисунок, формула, список литературы), а вся
   ГОСТ-вёрстка применяется автоматически на экспорте по
   выбранному профилю.

Полная двусторонняя совместимость: готовую `.docx` можно загрузить в
конструктор и редактировать дальше; собранный из конструктора документ
проходит нормоконтролем без дополнительных правок.

Оба режима работают через **единую модель документа** и **единую систему
профилей** — расхождений между «как пишем» и «как проверяем» нет.

## Статус

**115 проверок** в 16 категориях · **28 автофиксеров** · **31 CLI-команда** ·
**10 страниц веб-UI** (multi-page `st.navigation`) · **REST API на FastAPI** ·
**1791+ тестов** (`ruff check`, `ruff format`, `mypy --strict` чисты).

### Ядро

- **Парсер `.docx → Document`**. Поля и формат страницы, метаданные,
  параграфы со стилями и runs, заголовки H1..H4, таблицы (включая
  multi-row шапку через `<w:tblHeader/>` и merge-cells), рисунки,
  footer/header с полем `PAGE`, page numbering (`<w:pgNumType>` start
  + fmt), OMML-формулы → LaTeX, нумерованные/маркированные списки
  с уровнями, hyperlinks, footnotes, textboxes, библиография
  с распарсенными полями, DPI изображений, **комментарии рецензента**
  из `word/comments.xml`, **style-cascade** (font/size/bold/italic/color
  наследуются от Heading{N} → Normal).
- **Экспортёр `Document → .docx`**. Round-trip без потерь. Настоящие
  numPr-списки, корректная вёрстка по ГОСТу (чёрные заголовки Times
  New Roman вместо синего Cambria из шаблона Word, межабзацный
  интервал 0 pt). Multi-row шапка таблицы с авто-повтором на новых
  страницах (`<w:tblHeader/>`), опц. строка «Продолжение таблицы N».
  Ограничения по ширине **и высоте** рисунка (`max_height_cm`).
  Профильные форматы подписей (`caption.format`) уважаются.
- **Профили YAML** с deep-merge при `extends`. Базовый
  `gost-7.32-2017`, `gost-r-2.105-2019` (ЕСКД), пример кафедрального
  `example-department`. Типизированная Pydantic-схема со стилями
  страницы / текста / заголовков / таблиц / рисунков / списков и
  per-figure/table схемой нумерации (continuous / by_chapter /
  буквенно в приложениях).
- **115 проверок** в 16 категориях: F (страница), T (текст), S
  (структура), H (заголовки), I (рисунки), B (таблицы), M (формулы),
  L (списки), R (литература), C (перекрёстные ссылки), A
  (сокращения), P (приложения), K (колонтитулы), V (объём), X
  (стиль и стилистика), U (единицы измерения). Полный каталог —
  [docs/checks-catalog.md](docs/checks-catalog.md).
- **28 автофиксеров**: F.01–F.04/F.06 (геометрия страницы + позиция
  номера), T.01–T.14 (шрифт, кегль, интервалы, пробелы, кавычки,
  тире, NBSP), U.01/U.02/U.03 (единицы СИ: NBSP, пунктуация, точка
  после), H.01–H.04/H.08 (формат заголовков, нумерация, точка
  после/в конце), L.04. Применяются по `gostforge fix`, кнопкой
  «Применить автофиксы» в UI или `gostforge apply-fixes`.

### Конструктор работ

- **Fluent-API** (`gostforge.builder`) с тремя шаблонами:
  `coursework` / `bachelor_thesis` / `research_report`.
- **Отключение проверок** для отдельных разделов через
  `.skip_checks(*codes)` / `.skip_all_checks()` — для титульного,
  реферата, приложений.
- **Подразделы до 3-го уровня** через рекурсивный `.subsection(...)`.
- **Разложение готовой `.docx` в конструктор** (`document_to_state`)
  — импортированную работу можно редактировать дальше в UI или CLI.

### Streamlit-WebApp (`gostforge ui`)

Шесть режимов в одном приложении (переключатель в верху страницы):
**Главная** · **Нормоконтроль** · **Конструктор** · **Редактор
профиля** · **История** · **Документация**.

Конструктор включает:
- Загрузку готовой `.docx` со сразу показанной сводкой нарушений и
  кнопкой «Применить автофиксы».
- Кнопку «Собрать каркас по ГОСТ» — болванка структуры в один клик.
- Шаблоны разделов: Введение, Заключение, Реферат, Содержание,
  Список источников (`is_bibliography=True`), титульный лист (ручная
  вставка), приложения с авто-нумерацией букв (А, Б, В…), Глава с
  подразделом.
- Редактирование любого блока (параграф/таблица/рисунок/список/
  формула/TOC). Картинки вшиваются в state как data-URI.
- **Пословное редактирование параграфов** (Фаза 2.5): TextRun
  (B/I/U/sup/sub), InlineFormula (LaTeX), CrossRef (рисунок/таблица/
  формула), Citation (запись библиографии).
- **Многоуровневая шапка таблиц** через поле «Доп. шапка» с
  авто-склеиванием пустых ячеек (`Группа 1||Группа 2|` → две группы
  по 2 колонки).
- **Стабильные id блоков** — удаление/перемещение не «приклеивает»
  состояние виджета к соседу.
- Поиск-замена по разделам с подсветкой совпадений.
- Bulk-операции: удаление пустых параграфов, Title Case, авто-нумерация
  глав («1 Анализ», «1.1 Подраздел», «1.1.1 Пункт») со снятием
  нумерации со структурных разделов.
- Дублирование, перемещение и перенос разделов и блоков (в т. ч.
  в другой раздел).
- Панели **«Прогресс»**, **«Готовность работы»** (чек-лист
  обязательных элементов + навигация «Перейти к разделу»),
  **«Live-нормоконтроль»** с кнопкой «→ К разделу» на каждом
  нарушении.
- Раскрывающаяся панель «Нормоконтроль раздела»: чекбокс «Не
  проверять» и multi-select категорий проверок.
- Экспорт в `.docx`/`.pdf`/`.md`/`.html`; превью PDF в браузере
  (через LibreOffice headless).
- Undo/Redo + версионирование с автосохранением в
  `~/.gostforge/autosave/`.

**Редактор профиля** — визуальная настройка всех параметров оформления
(страница, текст, заголовки, таблицы — включая нумерацию и
«Продолжение таблицы», рисунки — включая `max_height_cm` и схему
нумерации, списки), набора проверок и метаданных. Сохранение профиля
снимком или наследником (`extends`); список и удаление пользовательских
профилей.

Подробнее — [docs/builder.md](docs/builder.md#4-визуальный-редактор-streamlit).

### CLI (30 команд)

| Команда | Назначение |
|---|---|
| `check` / `check-state` | Нормоконтроль `.docx` или state-файла |
| `fix` / `apply-fixes` | Автофиксы для `.docx` или state |
| `annotate` | Аннотация `.docx` комментариями Word или inline-маркерами |
| `new` / `new-state` | Болванка по шаблону → `.docx` или state |
| `import-docx` / `import-pdf` / `import-md` | Импорт в state (PDF: extra `[import-formats]`) |
| `generate` | state → `.docx` |
| `export-md` / `export-html` | state → Markdown / HTML5 |
| `convert` | Конвертация форматов через LibreOffice (DOC→DOCX) |
| `pdf` | `.docx` → PDF |
| `diff` / `diff-state` | Сравнение submission-ов или state-файлов |
| `stats [--by-section] [--json]` / `stats-state` | Метрики структуры |
| `state-versions` | Список и восстановление авто-версий state |
| `ui` | Streamlit-WebApp |
| `serve` | REST API на FastAPI |
| `history` | Submission-ы из локальной БД |
| `checks` | Список всех проверок |
| `doctor [--json]` | Диагностика окружения: версии deps, профили, LibreOffice |
| `profiles list/show/install/uninstall/validate/diff` | Управление профилями |
| `comment add/list/resolve/delete` | Комментарии руководитель↔студент |
| `plugins list/dir` | Управление пользовательскими плагинами проверок |

### REST API (опц. extra `[api]`)

13 endpoints на FastAPI: health, profiles, checks, check, fix,
annotate, stats, submissions + комментарии. Аутентификация через
`X-API-Key`, CORS, лимит размера файла. Запуск через
`gostforge serve` или `docker compose up`. Полный реестр — [docs/api.md](docs/api.md).

### Прочее

- **Локальная SQLite-БД** истории: `~/.gostforge/gostforge.db`,
  auto-init, миграции через `schema_version`.
- **Маркетплейс кафедральных профилей**:
  `gostforge profiles install kafedra.yaml` или `POST /profiles`.
- **Совместная работа руководитель ↔ студент**: комментарии с
  ролями, resolved-флаг, счётчик `unresolved_comments`.
- **Плагины проверок** (`~/.gostforge/plugins/`): пользовательские
  проверки через `@register("X.NN")` без модификации gostforge.
- **Production-деплой через Docker**: `Dockerfile` (API),
  `Dockerfile.ui` (Streamlit UI), `docker compose up -d` — multi-stage
  образы на `python:3.11-slim`.
- **CI на GitHub Actions**: тесты на Python 3.11/3.12, ruff/mypy,
  сборка Docker-образов.

Полный план развития — [docs/roadmap.md](docs/roadmap.md). История
изменений — [docs/changelog.md](docs/changelog.md).

## Архитектура (кратко)

```
┌─────────────────┐                                  ┌──────────────────┐
│  Конструктор UI │──┐                            ┌──│    Экспортёр     │──→ .docx
│  (для студента) │  │                            │  │  модель → .docx  │
└─────────────────┘  │                            │  └──────────────────┘
                     │   ┌────────────────────┐   │
                     ├──→│  Модель документа  │───┤
                     │   │ структура+контент  │   │
┌─────────────────┐  │   └────────────────────┘   │  ┌──────────────────┐
│     Парсер      │──┘            ↑               └──│    Валидатор     │──→ Отчёт
│ .docx → модель  │←── .docx      │                  │   115 проверок   │
└─────────────────┘               │                  └──────────────────┘
                                  │
                          ┌───────────────┐
                          │    Профили    │  (ГОСТ + наследники для кафедр)
                          └───────────────┘
```

Подробнее: [docs/architecture.md](docs/architecture.md).

## Установка (для разработки)

Требуется Python 3.11+.

```bash
git clone <ваш-репозиторий> gostforge
cd gostforge
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Опционально:
pip install -e ".[dev,ui]"             # Streamlit UI
pip install -e ".[dev,ui,api]"         # + REST API
pip install -e ".[dev,import-formats]" # + импорт PDF (pdfplumber)
```

## Использование

### Нормоконтроль

```bash
# Проверить одну работу с цветным выводом
gostforge check work.docx --profile gost-7.32-2017

# Папка работ → Excel-отчёт
gostforge check ./submissions/ --profile gost-7.32-2017 --report report.xlsx

# Кратко (только summary и коды нарушений)
gostforge check work.docx --quiet

# Markdown-отчёт (формат по расширению)
gostforge check work.docx --report report.md
```

Exit codes: `0` — нарушений нет; `1` — найдены ошибки; `2` — проблема
загрузки профиля.

### Автоисправление

```bash
gostforge fix work.docx -o work_fixed.docx
gostforge fix work.docx -o work_fixed.docx --only T.08 --only T.10
gostforge fix work.docx -o /dev/null --dry-run
```

### Конструктор работ (CLI)

```bash
# 1. Создать с нуля или импортировать готовую работу
gostforge new-state --template coursework --title "..." -o state.json
# ИЛИ
gostforge import-docx work.docx -o state.json
# ИЛИ из PDF (нужен extra [import-formats]):
gostforge import-pdf work.pdf -o state.json

# 2. Редактировать (вручную, в UI, или скриптом)
gostforge ui                                      # визуально
$EDITOR state.json                                # вручную
gostforge apply-fixes state.json -o state.json    # автофиксы

# 3. Сборка финального .docx
gostforge generate state.json -o final.docx

# Дополнительно: round-trip с Markdown и сравнение версий
gostforge export-md state.json -o draft.md
gostforge import-md draft.md -o state.json
gostforge diff-state old.json new.json
gostforge diff-state old.json new.json --mode unified
```

Доступные шаблоны: `coursework`, `bachelor_thesis`,
`research_report`, `empty`.

### Программный fluent-API

```python
from gostforge.builder import work

(
    work("Курсовая", author="Иван Иванов", year=2026)
    .section("Титульный лист")
        .paragraph("...")
        .skip_all_checks()
    .section("Введение")
        .paragraph("Актуальность темы исследования...")
        .list(["задача 1", "задача 2", "задача 3"], ordered=True)
    .section("Глава 1. Анализ")
        .subsection("1.1 Постановка задачи")
            .paragraph("...")
        .subsection("1.2 Существующие решения")
            .table(
                headers=["Алгоритм", "Сложность"],
                rows=[["Дейкстра", "O(n log n)"]],
                caption="Сложность алгоритмов",
            )
    .section("Заключение")
        .paragraph("...")
    .section("Список использованных источников")
        .reference("Иванов И. И. Программирование. — М. : Наука, 2023. — 320 с.")
    .save("coursework.docx")
)
```

См. [docs/builder.md](docs/builder.md) — полный гайд по builder-API
и UI.

### Веб-интерфейс

```bash
pip install -e ".[ui]"   # один раз
gostforge ui             # → http://localhost:8501
```

### PDF-экспорт

```bash
gostforge pdf work.docx -o work.pdf   # требует LibreOffice
```

### Аннотация документа

```bash
gostforge annotate work.docx -o annotated.docx          # комментарии Word
gostforge annotate work.docx -o annotated.docx --style inline  # inline-маркеры
```

## Плагины проверок

Кафедральные или организационные проверки подключаются как обычные
Python-файлы в `~/.gostforge/plugins/` (на Windows —
`%APPDATA%\gostforge\plugins\`). Функция, зарегистрированная через
`@register("X.NN")`, автоматически попадает в общий реестр и может
быть включена в любой профиль.

```bash
gostforge plugins dir    # узнать/создать каталог плагинов
gostforge plugins list   # увидеть загруженные плагины и их коды
```

Подробности и предупреждения о безопасности — [docs/plugins.md](docs/plugins.md).

## Документация

- [Архитектура](docs/architecture.md)
- [Каталог проверок](docs/checks-catalog.md)
- [Конструктор и визуальный редактор](docs/builder.md)
- [Система профилей](docs/profiles.md)
- [Плагины проверок](docs/plugins.md)
- [Колонтитулы и секции](docs/page-sections.md)
- [REST API](docs/api.md)
- [Локальная БД истории](docs/database.md)
- [Roadmap](docs/roadmap.md) · [Changelog](docs/changelog.md)
- [Как контрибьютить](CONTRIBUTING.md)

## Стандарты-основа

- **ГОСТ 7.32-2017** — Отчёт о НИР. Структура и правила оформления.
- **ГОСТ Р 2.105-2019** — ЕСКД. Общие требования к текстовым документам.
- **ГОСТ Р 7.0.100-2018** — Библиографическая запись. Описание.
- **ГОСТ Р 7.0.5-2008** — Библиографическая ссылка.
- **ГОСТ Р 8.000-2015** — Единицы измерения (СИ).

## Лицензия

MIT. См. [LICENSE](LICENSE).
