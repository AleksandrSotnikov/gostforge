# Roadmap

## Фаза 0 — Фундамент (завершена)

Цель достигнута: пайплайн `parse → validate → report` работает на
любом `.docx`.

- [x] Структура проекта, документация (`docs/architecture.md`,
      `docs/profiles.md`, `docs/checks-catalog.md`, `docs/builder.md`,
      `docs/page-sections.md`, `CONTRIBUTING.md`).
- [x] Schema модели документа (dataclass + `SCHEMA_VERSION`; Pydantic — профиль).
- [x] Парсер `.docx → Document`: поля страницы, метаданные, параграфы
      с runs, заголовки, поле PAGE в footer.
- [x] Минимальный экспортёр `Document → .docx`: поля страницы, стиль
      Normal, параграфы, заголовки.
- [x] Базовый профиль `gost-7.32-2017.yaml` с полноценным deep-merge
      при `extends`.
- [x] 5 ключевых проверок: F.01, F.04, T.01, T.02, S.01.
- [x] CLI `gostforge check` с юзер-френдли выводом, `profiles list`,
      `checks`.
- [x] Базовые синтетические фикстуры (`tests/conftest.py::make_docx`).

## Фаза 1 — MVP нормоконтроля + Конструктор (завершена)

Цель достигнута: оба режима системы работают, **69 проверок** в реестре,
**527+ тестов**.

### Парсер и модель

- [x] Парсер расширен на основные блоки: поля страницы, формат бумаги
      (A4/A3/A5/Letter/Legal), ориентация, метаданные, параграфы со
      стилями и runs, заголовки, таблицы и рисунки со склейкой подписей,
      header и footer с полем PAGE (`<w:fldSimple>` + `fldChar+instrText`),
      `<w:pgNumType>` (start и fmt), `<w:pageBreakBefore>` через цепочку
      стилей, секция «Список использованных источников» →
      `BibliographyEntry`, OMML-формулы (`<m:oMath>` → `Formula.latex`),
      нумерованные и маркированные списки → `ListBlock`,
      `<w:autoHyphenation>` из `settings.xml`.
- [x] Экспортёр: round-trip parse → export → parse без потерь по
      реализованным атрибутам (включая footer с полем PAGE, pgNumType,
      ориентацию, таблицы, реальные изображения через `add_picture`,
      ListBlock через стили `List Number`/`List Bullet`).

### Валидатор: 69 проверок

| Категория | Покрытие | Коды |
| --- | --- | --- |
| F (страница) | **6/6** | F.01–F.06 |
| T (текст) | **13/13** | T.01–T.13 |
| S (структура) | **8/8** | S.01–S.08 |
| H (заголовки) | 6/8 | H.01–H.05, H.08 |
| I (рисунки) | 4/10 | I.01, I.03, I.05, I.06 |
| B (таблицы) | 4/9 | B.01, B.03, B.08, B.09 |
| M (формулы) | **5/5** | M.01–M.05 |
| L (списки) | **4/4** | L.01–L.04 |
| R (литература) | 1/13 | R.04 |
| C (перекрёстные ссылки) | 3/5 | C.01, C.02, C.04 |
| A (сокращения) | 1/3 | A.01 |
| P (приложения) | 1/5 | P.01 |
| K (колонтитулы) | **6/6** | K.01–K.06 |
| V (объём) | **4/4** | V.01–V.04 |
| X (стиль) | 3/5 | X.01–X.03 |

**8 из 15 категорий закрыты полностью.**

### Автоисправление

- [x] `gostforge.fixer` — симметричный движок с реестром по коду проверки.
- [x] **8 фиксеров**: T.08 (двойные пробелы), T.09 (хвостовые пробелы),
      T.10 (типографские кавычки), T.11 (длинное тире), T.12 (NBSP между
      числом и единицей), T.13 (NBSP между инициалами), H.03 (точка
      после номера заголовка), H.08 (точка в конце заголовка).
- [x] CLI `gostforge fix file.docx -o fixed.docx` с `--only CODE`
      и `--dry-run`.

### Конструктор работ

- [x] **`gostforge.builder`** — fluent API: `WorkBuilder` +
      `SectionBuilder`. Методы: `.section()`, `.subsection()`,
      `.paragraph()`, `.figure(image_path, caption)`, `.image()`,
      `.table(headers, rows, caption)`, `.list(items, ordered)`,
      `.formula(latex, numbered)`, `.reference(entry)`.
- [x] Автонумерация рисунков, таблиц, формул на уровне builder.
- [x] Автопростановка `page_break_before=True` у не-первых разделов
      уровня 1 (для S.06).
- [x] Шаблоны `coursework`, `bachelor_thesis`, `research_report` —
      готовые скелеты с обязательными разделами.
- [x] CLI `gostforge new file.docx --template ... --title ... --year ...`.
- [x] Документ-болванка из коробки проходит ≥29 из 30 проверок
      (warning S.07 — ожидаемо для плейсхолдеров).

### Аннотация документа

- [x] `gostforge.annotator` — inline-комментарии прямо в `.docx`.
      Маркеры вида `[CODE: message]` курсивом красным цветом
      вставляются в начало проблемных параграфов.
- [x] CLI `gostforge annotate file.docx -o annotated.docx`.

### Профили

- [x] `gost-7.32-2017.yaml` — базовый, с параметрами для всех 69
      проверок.
- [x] `gost-r-2.105-2019.yaml` — профиль ЕСКД (узкое правое поле,
      нумерация со страницы 2, обязательный «Содержание»).
- [x] `example-department.yaml` — пример кафедрального наследника
      (кегль 12, отступ 1.0 см, нумерация с 4-й страницы).
- [x] Документация: 6-шаговый гайд по созданию собственного профиля
      в [docs/profiles.md](profiles.md).

### CLI

11 операций: `check`, `fix`, `annotate`, `new`, `stats`, `ui`,
`checks`, `profiles list/show/validate/diff`. Полный help — `gostforge --help`.

- [x] `--report report.xlsx` (Excel через openpyxl) и `--report report.md`
      (Markdown). Формат определяется по расширению.
- [x] `gostforge stats` — структурная статистика документа.
- [x] Цветной вывод с группировкой по `severity`, exit codes для CI.

### Streamlit-UI

- [x] `gostforge ui` запускает локальный веб-интерфейс.
- [x] Два режима: «Нормоконтроль» и «Конструктор».
- [x] В «Нормоконтроле» — три вкладки на каждый загруженный файл:
      Проверка / Статистика / Автоисправление со скачиванием
      исправленного `.docx`.
- [x] В «Конструкторе» — селект шаблона, поля метаданных, кнопка
      «Создать болванку» → скачивание `.docx`.

### Тестирование

- [x] 666+ unit-тестов; все проходят на каждом коммите.
- [x] Синтетические фикстуры через `tests/conftest.py::make_docx`.
- [~] Регрессионный набор из 20+ реальных анонимизированных работ —
      собирается с пилотной кафедрой (требует данных от пользователей).

## Фаза 2 — Расширение покрытия и продакшен (завершена)

**Покрытие каталога: 104 проверки (100%).** Все 15 категорий закрыты
полностью: F (6), T (13), S (8), H (8), I (10), B (9), M (5), L (4),
R (13), C (5), A (3), P (5), K (6), V (4), X (5).

- [x] **+10 проверок** до полного покрытия: H.06, H.07, I.02/I.04/I.07/I.10,
      B.02/B.04–B.07.
- [x] **+8 проверок** в категории B (таблицы) — все 9 теперь реализованы.
- [x] **+10 проверок**: A.02/A.03, P.02–P.05, C.03/C.05, X.04/X.05.
- [x] **I.08** (DPI ≥ 150) — парсер извлекает DPI из embedded media через Pillow.
- [x] **I.09** (центрирование рисунка) — парсер сохраняет alignment.
- [x] **R.01–R.13** — все 13 проверок литературы, включая порядок,
      обязательные поля, даты обращения, DOI, свежесть, подозрительные
      домены. Парсер расширен на распознавание полей
      `BibliographyEntry.fields` (author, year, url, doi, access_date,
      place, language) по ГОСТ Р 7.0.100-2018.
- [x] **9 фиксеров** автоисправления: T.07–T.13, H.03, H.08.
- [x] CLI расширен: `gostforge profiles validate`, `gostforge profiles diff`.
- [x] Парсер: `embedded:rIdN` для изображений, чтение `<m:oMath>` формул,
      `<w:autoHyphenation>` из settings.xml.

Осталось на следующие итерации:

- [ ] **Аннотатор**: настоящие OOXML-комментарии Word
      (`<w:commentRangeStart>` + `comments.xml`-part), не только
      inline-маркеры.
- [ ] **Конструктор**: визуальный редактор (PyQt6 или Tauri+Web)
      поверх существующего fluent-API.
- [ ] **Экспортёр**: формулы (LaTeX → OMML), реальные изображения
      из `Figure.image_path` в media-папку docx, корректные PageSection
      с разными колонтитулами через `sectPr` и отдельные header/footer-parts.
- [ ] **Плагины проверок**: динамическая загрузка из
      `~/.gostforge/plugins/`.
- [ ] **Экспорт PDF** через LibreOffice headless.
- [ ] **Регрессионный набор** из 20+ реальных анонимизированных
      работ от пилотной кафедры.

## Фаза 2.5 — Пословное редактирование в визуальном конструкторе (завершена)

> **Статус:** реализована.
> **Полная спецификация:** [docs/phase-2.5-spec.md](phase-2.5-spec.md).

Цель достигнута: редактирование контента в визуальном конструкторе
переведено с уровня «целый абзац строкой» на уровень
**inline-элементов** — форматированный фрагмент, перекрёстная ссылка,
inline-формула, библиографическая цитата.

Реализовано:

- [x] **Модель:** новые типы `InlineFormula`, `Citation`,
      `CrossRef.prefix`, `TextRun.underline`, `TextRun.color_hex`;
      bump `SCHEMA_VERSION → 0.3.0`.
- [x] **Builder:** `SectionBuilder.rich_paragraph(elements)` рядом
      с существующим `.paragraph(text)` (тонкая обёртка).
- [x] **Экспортёр:** inline-формулы (`<m:oMath>` внутри `<w:r>`),
      `<w:fldSimple w:instr=" REF target_id \h "/>` для CrossRef с
      опц. prefix-run, текстовые run-ы «[N]» / «[N, с. P]» для
      Citation. Bibliography-индекс через
      module-level `_current_bibliography_index`.
- [x] **Парсер:** распознавание inline-формул (m:oMath без oMathPara),
      эвристика для цитат `[N]` / `[N, с. P]` в TextRun-ах (только при
      валидном N), извлечение CrossRef.prefix из предыдущего run,
      чтение `<w:u>` и `<w:color>`.
- [x] **UI:** полноценный inline-редактор параграфа
      (`_render_paragraph_inline_editor`) — список run-ов с
      собственными редакторами, кнопками ↑/↓/× и панелью добавления
      (+ Текст / + Формула / + Ссылка / + Цитата).
- [x] **Совместимость:** `_normalize_paragraph_state` —
      `{kind: paragraph, text: ...}` из Phase 2 автоматически
      конвертируется в `{kind: paragraph, runs: [...]}`.
- [x] **Undo/Redo:** кольцевой буфер на 50 snapshot-ов, ленивый
      `_auto_snapshot_if_changed`, кнопки в sidebar с правильным
      disabled-состоянием, обратимое branch-and-truncate.
- [x] **Auto-save:** `~/.gostforge/autosave/last-session.json`, не
      чаще раза в 30 секунд, баннер восстановления при старте UI
      (если файл свежее 24 часов и state ещё дефолтный).
- [x] **Тесты:** **+97 новых** (8 model + 6 builder + 10 exporter +
      14 parser + 23 web-state + 13 web-editor + 13 undo/redo +
      10 autosave). Общая база — **843 теста**.
- [x] **Документация:** `docs/builder.md §4.1 «Пословное
      редактирование»` с таблицами и примерами,
      `docs/architecture.md` с таблицей InlineElement ↔ OOXML, README.

**Definition of Done выполнен:** round-trip state → `Document` →
`.docx` → парс → state без потерь inline-элементов, генерируемая
конструктором работа проходит проверки `gost-7.32-2017` без
регрессий, mypy --strict baseline не сдвинулся.

## Фаза 3 — Продакшен и масштаб — по мере спроса

- [x] **REST API (FastAPI)** для интеграций с LMS. 7 endpoints
      (`/health`, `/profiles[/{id}]`, `/checks`, `/check`, `/fix`,
      `/annotate`, `/stats`), CLI-обёртка `gostforge serve`,
      опциональная зависимость `[api]`. Спецификация:
      [phase-3-api-spec.md](phase-3-api-spec.md).
- [x] **Аутентификация API-key** через middleware (env
      `GOSTFORGE_API_KEYS`, поддержка нескольких ключей, bypass для
      `/health` и `/docs`). Rate-limiting — на стороне reverse-proxy
      (готовый nginx-конфиг в [api.md](api.md)).
- [x] **Docker и docker-compose** для production-деплоя.
      Multi-stage Dockerfile (API) и Dockerfile.ui (Streamlit UI),
      docker-compose с двумя сервисами, non-root юзер, HEALTHCHECK,
      лимит ресурсов. Руководство по деплою с nginx — [api.md](api.md).
- [x] **Streamlit-UI как Docker-сервис** — Dockerfile.ui +
      сервис в docker-compose. UI работает автономно (не требует
      REST API). Аутентификация — через reverse-proxy (basic auth
      или oauth2-proxy).
- [x] **CI на GitHub Actions** — тесты на Python 3.11/3.12 (matrix),
      ruff/mypy в warn-only режиме, сборка обоих Docker-образов,
      валидация docker-compose.yml. concurrency.group отменяет
      устаревшие прогоны.
- [x] **Локальная SQLite-БД с auto-init**. Stdlib sqlite3, ноль
      внешних зависимостей. Путь `~/.gostforge/gostforge.db` или env
      `GOSTFORGE_DB_PATH`; каталог и схема создаются автоматически
      через `schema_version`-таблицу + append-only список миграций.
      Подробное руководство — [database.md](database.md).
- [x] **История проверок (submissions)**. Каждый `gostforge check`
      и `POST /check` опционально (по умолчанию вкл.) записывает
      submission + все violations в БД. Просмотр через
      `gostforge history [--limit N] [--filename F] [--id N]` и
      `GET /submissions[/{id}]`. DELETE для очистки. Persistence
      между перезапусками Docker — через named volume
      `gostforge-data`.
- [ ] Командная работа: руководитель ↔ студент (комментарии,
      обсуждения, итерации).
- [ ] Интеграция с LMS (Moodle, eLearning, и др.) — теперь
      технически возможна через REST API.
- [ ] Маркетплейс профилей кафедр — публичный реестр.
- [ ] Мобильные клиенты для просмотра отчётов.

## Принципы планирования

1. **Каждая фаза даёт рабочий продукт.** Не «недостроенная фаза 2»,
   а «работает то, что обещано в фазе 1».
2. **Парсер — критический путь.** Без надёжного парсера всё
   остальное теоретическое.
3. **Профили — собираются на реальных кафедрах.** Не выдумываем
   «возможные» профили, добавляем по запросу.
4. **Регрессионные тесты обязательны.** Без 20+ реальных фикстур к
   концу Фазы 2 — стоп, собираем данные с пилотной кафедры.
5. **Параллельная разработка через worktree-агентов** доказала
   эффективность: 4 агента + 1 интегратор за итерацию дают ~+20
   проверок и ~+90 тестов.
