# gostforge

**Конструктор и нормоконтролёр документов по ГОСТу.**

Инструмент для двух сценариев:

1. **Нормоконтроль** — автоматическая проверка чужих `.docx` (курсовых, дипломных, ВКР, отчётов о НИР) на соответствие ГОСТ 7.32-2017, ГОСТ Р 2.105-2019, ГОСТ Р 7.0.100-2018 и/или методичкам кафедр. Результат — отчёт + аннотированный `.docx` с комментариями Word ровно в проблемных местах.
2. **Конструктор** — структурный редактор для написания работ с нуля. Студент собирает документ из блоков (раздел, абзац, таблица, рисунок, формула, список литературы), а вся ГОСТ-вёрстка применяется автоматически на экспорте по выбранному профилю.

Между двумя режимами полная двусторонняя совместимость: готовую `.docx` можно загрузить в конструктор и редактировать дальше; собранный из конструктора документ — пройти нормоконтролем без дополнительных правок.

Оба режима работают с **единой моделью документа** и **единой системой профилей**, что исключает расхождения между «как пишем» и «как проверяем».

## Статус

**113 проверок в 16 категориях**, **18 автофиксеров**, **1500+ тестов**.

Что уже работает:

### Ядро
- **Парсер `.docx → Document`**: поля страницы, формат бумаги (A4/A3/A5/Letter/Legal), ориентация, метаданные, параграфы со стилями и runs, заголовки H1..H4, таблицы и рисунки со склейкой подписей, footer/header с полем PAGE, `<w:pgNumType>` (start + fmt), `<w:pageBreakBefore>`, OMML-формулы → `latex`, нумерованные и маркированные списки с распознаванием уровней (`<w:numPr><w:ilvl/>`), `<w:autoHyphenation>`, библиография с распарсенными полями (author, year, url, doi, access_date, place, language), DPI изображений через Pillow, alignment рисунков, **комментарии рецензента** из `word/comments.xml`, **style-cascade** (font/size/bold/italic/color наследуются от Heading{N} → Normal даже без явных run-атрибутов).
- **Экспортёр `Document → .docx`**: round-trip без потерь, **настоящие numPr-списки** с `numbering.xml` и одноуровневая/многоуровневая нумерация (`item_levels`), компактный отступ маркер↔текст (`<w:suff w:val="space"/>` вместо Tab), **корректная вёрстка по ГОСТу**: чёрные заголовки Times New Roman (а не синие Cambria из шаблона Word), `<w:tblBorders>` у всех таблиц, центрированные подписи рисунков и левые подписи таблиц, межабзацный интервал 0 pt (без наследованных 10 pt от Word-defaults).
- **Профили YAML** с полноценным наследованием (deep-merge): базовый `gost-7.32-2017`, `gost-r-2.105-2019` (ЕСКД), пример кафедрального `example-department`. Типизированная Pydantic-схема включает `HeadingStyleProfile`, `CaptionStyleProfile`, `TableStyleProfile`, `FigureStyleProfile`, `ListStyleProfile`, `BodyTextProfile` (с `space_before_pt`/`space_after_pt`).
- **113 реализованных проверок** в 16 категориях: F (страница), T (текст, вкл. T.14 — интервалы между абзацами), S (структура), H (заголовки, вкл. проверку цвета H.01/H.02), I (рисунки), B (таблицы, вкл. B.10 — пустые), M (формулы), L (списки), R (литература, вкл. R.14 — формат DOI/URL), C (перекрёстные ссылки), A (сокращения), P (приложения), K (колонтитулы), V (объём), X (стиль, вкл. X.06-X.08 — канцеляризмы/длинные предложения/повторы), U (единицы измерения, ГОСТ Р 8.000-2015). Полный каталог — [docs/checks-catalog.md](docs/checks-catalog.md).
- **18 автофиксеров**: безопасные правки (T.03–T.14, H.03/H.04/H.08, L.04, F.04/F.06). Применяются по `gostforge fix`, кнопкой «Применить автофиксы» в UI или `gostforge apply-fixes`.

### Конструктор работ
- **Fluent-API** (`gostforge.builder`) с тремя шаблонами (`coursework`/`bachelor_thesis`/`research_report`).
- **Отключение проверок для отдельных разделов** через `.skip_checks(*codes)` / `.skip_all_checks()` — нужно для титульного, реферата, приложений, оформляемых по своим правилам.
- **Подразделы до 3-го уровня** через рекурсивный `.subsection(...)`.
- **Разложение готовой .docx в конструктор** (`document_to_state`) — импортированную работу можно редактировать дальше как через UI, так и через CLI.

### CLI (30 команд)
| Команда | Что делает |
|---|---|
| `gostforge check` | Прогон нормоконтроля с цветным отчётом / Excel / Markdown |
| `gostforge fix` | Применение автофиксов |
| `gostforge annotate` | Аннотация .docx настоящими комментариями Word |
| `gostforge new` | Болванка работы по шаблону → .docx |
| `gostforge new-state` | То же, но в JSON-state для конструктора |
| `gostforge import-docx` | Разложить готовую работу в JSON-state |
| `gostforge import-pdf` | Извлечь структуру PDF в JSON-state (extra `[import-formats]`) |
| `gostforge generate` | JSON-state → .docx |
| `gostforge export-md` | JSON-state → Markdown (GFM, bold/italic, таблицы, формулы) |
| `gostforge import-md` | Markdown → JSON-state (round-trip с export-md) |
| `gostforge export-html` | JSON-state → HTML5 (standalone с CSS под печать / fragment) |
| `gostforge apply-fixes` | Автофиксы прямо над state-файлом |
| `gostforge diff-state` | Сравнение двух state — summary или unified diff |
| `gostforge stats-state` | Метрики state без .docx (разделы, слова, --json) |
| `gostforge check-state` | Нормоконтроль над state без .docx (быстро, exit 1 при ошибках) |
| `gostforge state-versions` | Список/восстановление авто-версий state |
| `gostforge convert` | Конвертация форматов через LibreOffice (DOC→DOCX и др.) |
| `gostforge pdf` | .docx → PDF через LibreOffice |
| `gostforge diff` | Сравнение двух submission-ов из истории |
| `gostforge stats` | Числовые метрики структуры документа |
| `gostforge ui` | Запуск Streamlit-WebApp |
| `gostforge serve` | Запуск REST API на FastAPI |
| `gostforge history` | Просмотр submission-ов из локальной БД |
| `gostforge checks` | Список всех проверок |
| `gostforge profiles list/show/install/uninstall/validate/diff` | Управление профилями |
| `gostforge comment add/list/resolve/delete` | Комментарии руководитель↔студент |
| `gostforge plugins list/dir` | Управление пользовательскими плагинами проверок |

### Streamlit-WebApp
Шесть режимов в одном приложении (переключатель вверху страницы) — открывается на `localhost:8501` через `gostforge ui`:
- **Главная** — обзор, быстрый старт, шпаргалка по ГОСТ 7.32 и метрики (число проверок / профилей).
- **Нормоконтроль** — проверка `.docx` по выбранному профилю.
- **Конструктор** — сборка работы по ГОСТу из блоков.
- **Редактор профиля** — настройка параметров оформления, проверок и метаданных профиля.
- **История** — прошлые проверки и обсуждение руководитель↔студент.
- **Документация** — встроенное руководство.

**Конструктор** содержит:
- **Загрузка готовой работы** (`Загрузить .docx в конструктор`) с сразу показанной сводкой нарушений нормоконтроля и кнопкой **«Применить автофиксы»**.
- **Кнопка «Собрать каркас по ГОСТ»** — болванка структуры в один клик.
- **Шаблоны разделов** в один клик: Введение, Заключение, Реферат, Содержание, Список источников (с `is_bibliography=True`), **титульный лист** для ручной вставки, **приложения** с авто-нумерацией букв (А, Б, В…), Глава с подразделом.
- **Редактирование блоков** на любой глубине: параграфы, таблицы, рисунки, списки, формулы, оглавление. Картинки вшиваются прямо в state.
- **Пословное редактирование параграфов** на уровне inline-элементов: TextRun (B/I/U/sup/sub), InlineFormula (LaTeX inline), CrossRef (выбор рисунка/таблицы/формулы из списка), Citation (выбор записи библиографии с опц. страницами).
- **Поиск-замена по разделам** с подсветкой совпадений (заголовки, тексты параграфов, подписи таблиц/рисунков, элементы списков, ссылки).
- **Bulk-операции**: удалить пустые параграфы, заголовки в Title Case, авто-нумерация глав («1 Анализ», «1.1 Подраздел», «1.1.1 Пункт») со снятием нумерации со структурных разделов (Введение/Заключение/Приложение/etc), сброс всех `disabled_checks`.
- **Дублирование** и **перемещение разделов** через выпадающий список «Новая позиция».
- **Панель «Прогресс работы»**: счётчики заполненных разделов / параграфов / таблиц / рисунков / источников / слов.
- **Панель «Готовность работы»**: чек-лист обязательных структурных элементов (титульник / содержание / введение / основная часть / заключение / список источников / приложения) + навигация «Перейти к разделу».
- **Live-нормоконтроль** в main-области — постоянная сводка нарушений, обновляется при каждом изменении.
- **Раскрывающаяся панель «Нормоконтроль раздела»** в редакторе каждого раздела — чекбокс «Не проверять» и multi-select по категориям (F-Поля, T-Типографика, H-Заголовки, S-Структура, R-Источники, B-Библиография, I-Рисунки, L-Списки, C-Перекрёстные ссылки, M-Формулы, A-Сокращения, K-Колонтитулы, V-Объём, P-Приложения).
- **Экспорт** в `.docx`/`.pdf`/`.md`/`.html`; **превью PDF** прямо в браузере (через LibreOffice headless).
- **Панель импортированных комментариев рецензента** — если в загруженной работе были комментарии Word, они показываются в одном месте.
- **Undo/Redo** + версионирование с автосохранением в `~/.gostforge/autosave/`.

**Редактор профиля** — визуальная настройка всех параметров оформления (страница, текст, заголовки, таблицы, рисунки, списки), набора проверок и метаданных. Сохранение профиля снимком или наследником (`extends`); список и удаление пользовательских профилей.

Подробнее — [docs/builder.md](docs/builder.md#4-визуальный-редактор-streamlit).

Остальные режимы:
- **Главная** — обзор возможностей, быстрый старт, шпаргалка по ГОСТ 7.32 и метрики (число проверок / профилей).
- **Нормоконтроль** — drag-and-drop, сводка по severity, цветной отчёт + Excel/Markdown, автофиксы, скачивание аннотированной версии и PDF.
- **История** — список прошлых проверок из локальной БД с цветным summary, фильтрами и встроенной лентой обсуждения руководитель↔студент.
- **Документация** — встроенный просмотр всех руководств `docs/*.md` с навигацией.

### REST API (опц. extra `[api]`)
13 endpoints на FastAPI: `/health`, `/profiles`, `/profiles/{id}`, `/checks`, `/check`, `/fix`, `/annotate`, `/stats`, `/submissions`, `/submissions/{id}`, комментарии (`POST/GET /submissions/{id}/comments`, `PATCH /comments/{id}/resolve`, `DELETE /comments/{id}`). Аутентификация через `X-API-Key`, CORS, лимит размера файла. Запуск через `gostforge serve` или `docker compose up`.

### Прочее
- **Локальная SQLite-БД** истории: `~/.gostforge/gostforge.db`, auto-init, миграции через `schema_version`.
- **Маркетплейс кафедральных профилей**: `gostforge profiles install kafedra.yaml` или `POST /profiles`.
- **Совместная работа руководитель ↔ студент**: комментарии с ролями, resolved-флаг, счётчик `unresolved_comments`.
- **Плагины проверок** (`~/.gostforge/plugins/`): пользовательские проверки через `@register("X.NN")` без модификации gostforge.
- **Production-деплой через Docker**: `Dockerfile` (API), `Dockerfile.ui` (Streamlit UI), `docker compose up -d` — multi-stage образы на `python:3.11-slim`.
- **CI на GitHub Actions**: тесты на Python 3.11/3.12, ruff/mypy, сборка Docker-образов.

См. [docs/roadmap.md](docs/roadmap.md) — план фаз и текущий прогресс.

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
│ .docx → модель  │←── .docx      │                  │   113 проверок   │
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

Exit codes: `0` — нарушений нет; `1` — найдены ошибки; `2` — проблема загрузки профиля.

### Автоисправление

```bash
# Все безопасные правки → новый файл
gostforge fix work.docx -o work_fixed.docx

# Только конкретные коды
gostforge fix work.docx -o work_fixed.docx --only T.08 --only T.10

# Dry-run без записи
gostforge fix work.docx -o /dev/null --dry-run
```

Исправляется: двойные пробелы (T.08), хвостовые пробелы (T.09), прямые кавычки → ёлочки (T.10), дефис между пробелами → длинное тире (T.11), точка после номера в заголовке (H.03), точка в конце заголовка (H.08), **интервалы между абзацами** (T.14), и ещё.

### Конструктор работ (CLI)

**Стартовая болванка через шаблон:**
```bash
# Создать .docx-болванку
gostforge new my-coursework.docx --template coursework \
    --title "Анализ алгоритмов" --author "Иванов И. И." --year 2026

# Или JSON-state для редактирования в UI
gostforge new-state --template coursework \
    --title "Анализ" --author "Иванов И. И." --year 2026 \
    -o draft.json
```

Доступные шаблоны: `coursework`, `bachelor_thesis`, `research_report`, `empty`.

**Полный CLI-цикл редактирования:**
```bash
# 1. Создать с нуля или импортировать готовую работу
gostforge new-state --template coursework --title "..." -o state.json
# ИЛИ
gostforge import-docx work.docx -o state.json
# ИЛИ из PDF (нужен extra [import-formats]):
gostforge import-pdf work.pdf -o state.json

# 2. Редактировать (вручную, в UI, или скриптом)
gostforge ui                          # визуально
$EDITOR state.json                    # вручную
gostforge apply-fixes state.json -o state.json  # автофиксы

# 3. Сборка финального .docx
gostforge generate state.json -o final.docx

# Дополнительно: экспорт в Markdown для git-ревью или Obsidian
gostforge export-md state.json -o draft.md
gostforge import-md draft.md -o state.json

# Сравнение версий
gostforge diff-state old.json new.json              # summary
gostforge diff-state old.json new.json --mode unified  # построчно
```

### Программный fluent-API

```python
from gostforge.builder import work

(
    work("Курсовая", author="Иван Иванов", year=2026)
    .section("Титульный лист")
        .paragraph("...")
        .skip_all_checks()  # титульный не проверяем нормоконтролем
    .section("Введение")
        .paragraph("Актуальность темы исследования...")
        .list(["задача 1", "задача 2", "задача 3"], ordered=True)
    .section("Глава 1. Анализ")
        .subsection("1.1 Постановка задачи")
            .paragraph("...")
        .subsection("1.2 Существующие решения")
            .paragraph("...")
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

См. [docs/builder.md](docs/builder.md) — полный гайд по builder-API и UI.

### Веб-интерфейс

```bash
pip install -e ".[ui]"   # один раз
gostforge ui             # → http://localhost:8501
```

В верхнем переключателе режима — «Главная», «Нормоконтроль», «Конструктор», «Редактор профиля», «История», «Документация».

### PDF-экспорт

```bash
# Требует LibreOffice (sudo apt install libreoffice)
gostforge pdf work.docx -o work.pdf
```

### Аннотация документа

```bash
# Настоящие комментарии Word (боковые выноски, можно резолвить)
gostforge annotate work.docx -o annotated.docx

# Inline-маркеры [F.01: текст] красным курсивом прямо в тексте
gostforge annotate work.docx -o annotated.docx --style inline
```

## Плагины проверок

Кафедральные или организационные проверки можно подключать в виде **плагинов** — обычных Python-файлов в каталоге `~/.gostforge/plugins/` (`%APPDATA%\gostforge\plugins\` на Windows). Каждая зарегистрированная через `@register("X.NN")` функция автоматически попадает в общий реестр и может быть включена в любой профиль.

```bash
gostforge plugins dir    # узнать/создать каталог плагинов
gostforge plugins list   # увидеть загруженные плагины и их коды
```

Гайд с примерами и предупреждениями о безопасности — [docs/plugins.md](docs/plugins.md).

## Документация

- [Архитектура](docs/architecture.md)
- [Каталог проверок](docs/checks-catalog.md)
- [Конструктор и визуальный редактор](docs/builder.md)
- [Система профилей](docs/profiles.md)
- [Плагины проверок](docs/plugins.md)
- [Колонтитулы и секции](docs/page-sections.md)
- [REST API](docs/api.md)
- [Локальная БД истории](docs/database.md)
- [Roadmap](docs/roadmap.md)
- [Работа с Claude Code](docs/claude-code-workflow.md)
- [Вклад в проект](CONTRIBUTING.md)

## Стандарты-основа

- **ГОСТ 7.32-2017** — Отчёт о научно-исследовательской работе. Структура и правила оформления.
- **ГОСТ Р 2.105-2019** — ЕСКД. Общие требования к текстовым документам.
- **ГОСТ Р 7.0.100-2018** — Библиографическая запись. Библиографическое описание.
- **ГОСТ Р 7.0.5-2008** — Библиографическая ссылка.

## Лицензия

MIT. См. [LICENSE](LICENSE).
