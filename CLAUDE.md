# Контекст проекта для Claude Code

> Этот файл автоматически читается Claude Code в начале каждой
> сессии. Содержит главное, что нужно знать перед изменением кода.

## Что это за проект

`gostforge` — двухрежимная Python-система:
1. **Нормоконтроль** чужих `.docx` (курсовых, дипломных, ВКР) на
   соответствие ГОСТ.
2. **Конструктор** документов для написания работ по ГОСТу с нуля.

Оба режима работают через **единую модель документа**
(`src/gostforge/model/`).

## Стандарты, на которых построен проект

- ГОСТ 7.32-2017 — отчёты о НИР, основа.
- ГОСТ Р 2.105-2019 — общие требования к текстовым документам.
- ГОСТ Р 7.0.100-2018 — библиографическое описание.
- ГОСТ Р 8.000-2015 — единицы измерения (категория проверок `U.*`).

## Текущее состояние

**118 проверок** в 16 категориях · **35 автофиксеров** · **30 CLI-команд** ·
**6 режимов веб-UI** · **REST API на FastAPI** · **1654+ тестов**
(`ruff check`, `ruff format`, `mypy --strict` чисты).

Актуальный реестр проверок — `gostforge checks`. План того, что
делать дальше — `docs/roadmap.md`. История значимых изменений —
`docs/changelog.md`.

## Стек

- Python 3.11+
- `python-docx` + `lxml` — работа с OOXML
- `pydantic` — схемы профилей
- `pyyaml` — загрузка профилей
- `click` — CLI
- `streamlit` — веб-интерфейс (опц. extra `[ui]`)
- `fastapi` + `uvicorn` — REST API (опц. extra `[api]`)
- `openpyxl` — Excel-отчёты
- `pdfplumber` — импорт PDF (опц. extra `[import-formats]`)
- `pytest` — тесты, `ruff` — линтинг, `mypy --strict` — типы

## Структура

```
src/gostforge/
├── model/          # Модель документа (центральный контракт, dataclass)
├── profile/        # Pydantic-схема профилей + загрузка YAML с deep-merge
├── parser/         # .docx → Document (python-docx + lxml)
├── exporter/       # Document → .docx
├── validator/      # Движок проверок: engine + checks/{F,T,S,H,I,B,M,L,R,C,A,P,K,V,X,U}
├── fixer/          # Автоисправление: симметричный движок к валидатору
├── builder/        # Конструктор работ: WorkBuilder + шаблоны + section_builder
├── pdf_exporter.py # .docx → PDF через LibreOffice (опц.)
├── pdf_importer/   # PDF → state через pdfplumber (опц.)
├── stats.py        # compute_stats(Document) → DocumentStats
├── db/             # SQLite-БД истории submissions + комментариев
├── api/            # FastAPI-приложение (опц.)
├── web/            # Streamlit-приложение (опц.): app, builder_editor, profile_editor, ...
└── cli.py          # Точка входа `gostforge` (30 команд)

profiles/           # YAML-профили (base + примеры наследников)
tests/              # pytest (fixtures/ под gitignore для реальных .docx)
docs/               # architecture, checks-catalog, builder, profiles, api, ...
```

## Ключевые архитектурные правила

1. **Модель — это контракт.** Любое изменение
   `src/gostforge/model/` затрагивает парсер, экспортёр и валидатор
   одновременно. Меняешь модель — обновляй `SCHEMA_VERSION` и
   убеждайся в back-compat (новые поля с default-значениями).
2. **Проверки изолированы.** Каждая проверка — отдельная функция,
   зарегистрированная через `@register("CODE")`. Знает только про
   `Document` и `Profile`, ничего про парсер/экспортёр.
3. **Автофиксер симметричен проверке.** Если в `validator/checks/X.py`
   есть `@register("X.NN")`, фиксер живёт в `fixer/fixers/X.py` с
   таким же кодом и реиспользует предикат проверки (через локальный
   импорт), чтобы исправлять ровно то, что находит валидатор.
   Правит только **явные** атрибуты (`run.font == "Cambria"` —
   правим; `run.font is None` — наследуется от стиля, не трогаем).
4. **Профили — это данные, не логика.** Сложные правила
   реализуются как функции-проверки, параметризуемые через `params`
   в YAML. В самих YAML не должно быть кода или скриптов.
5. **PageSection ≠ Section.** `PageSection` — секция вёрстки с
   собственными колонтитулами и геометрией. `LogicalSection` (или
   «Section» в обиходе) — раздел работы по содержанию (введение,
   глава 1). См. `docs/page-sections.md`.
6. **Регрессионные тесты обязательны.** Каждая новая проверка,
   эвристика парсера или автофиксер сопровождается фикстурой и
   тестом. Реальные студенческие работы в публичный репозиторий не
   коммитятся — только анонимизированные синтетические кейсы в
   `tests/fixtures/synthetic/`.

## Конвенции кода

- Type hints везде, `mypy --strict` обязан проходить.
- Форматирование: `ruff format`. Линтинг: `ruff check`.
- Имена идентификаторов — на английском. Docstrings и комментарии —
  на русском.
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`,
  `test:`, `chore:`. Сообщения коммитов — на русском или английском
  по вкусу.

## Команды

```bash
# Установка для разработки
pip install -e ".[dev]"
pip install -e ".[dev,ui]"            # + Streamlit UI
pip install -e ".[dev,ui,api]"        # + REST API
pip install -e ".[dev,import-formats]"  # + импорт PDF

# Тесты — ВАЖНО: только `python -m pytest`, не голый `pytest`
# (в окружении pytest не всегда видит editable-копию пакета).
python -m pytest -q                          # все тесты
python -m pytest tests/test_validator.py -v  # конкретный модуль
python -m pytest -k "F_01"                   # по имени теста

# В worktree агента (если pytest не находит модуль gostforge):
PYTHONPATH=$(pwd)/src python -m pytest -q

# Проверка типов и стиля (должны проходить перед коммитом)
ruff check src tests
ruff format src tests
mypy src

# CLI (основные подкоманды)
gostforge check work.docx --profile gost-7.32-2017
gostforge fix work.docx -o fixed.docx [--only T.08] [--dry-run]
gostforge new my-coursework.docx --template coursework
gostforge stats work.docx
gostforge profiles list / show <id>
gostforge checks
gostforge ui                                # веб-интерфейс
gostforge serve                             # REST API
```

## Что нельзя

- **Не коммитить реальные .docx студентов** в `tests/fixtures/` или
  куда-либо ещё. Только обезличенные синтетические фикстуры в
  `tests/fixtures/synthetic/`.
- **Не помещать персональные данные** (ФИО, email, телефоны) в код,
  тесты, фикстуры, документацию.
- **Не использовать `print()`** в библиотечном коде. Только через
  `logging` или возврат структурированных объектов. `print` допустим
  только в `cli.py`.
- **Не делать массовые правки автоматическим путём** без явного
  одобрения пользователя: запуск `ruff format` на всё дерево,
  переименование пакетов, изменение модели без миграции.
- **Не понижать строгость mypy** ради быстрого прохождения проверок.
  Если тип сложный — описать его, а не использовать `Any`.

## Куда смотреть, когда непонятно

- Общая архитектура → `docs/architecture.md`
- Какие проверки и что они делают → `docs/checks-catalog.md`
- Конструктор и UI → `docs/builder.md`
- Структура и наследование профилей → `docs/profiles.md`
- Колонтитулы и `sectPr` → `docs/page-sections.md`
- REST API → `docs/api.md`
- Локальная БД истории → `docs/database.md`
- Плагины проверок → `docs/plugins.md`
- Что делать дальше → `docs/roadmap.md`
- История изменений → `docs/changelog.md`
- Как контрибьютить → `CONTRIBUTING.md`

## Полезные эвристики для расширения

**При добавлении проверки:**
1. Найди код проверки в `docs/checks-catalog.md`, проверь категорию.
2. Открой соответствующий файл в `src/gostforge/validator/checks/`
   (или создай новый).
3. Зарегистрируй функцию через `@register("X.NN")`.
4. Добавь импорт нового модуля в
   `src/gostforge/validator/checks/__init__.py`.
5. Включи проверку в `profiles/gost-7.32-2017.yaml`.
6. Напиши минимум 2 теста: «всё хорошо» (нет violation) и
   «нарушение найдено».
7. Обнови `docs/checks-catalog.md` и счётчик в README.

**При добавлении автофиксера:**
1. Найди парную проверку в `validator/checks/X.py`.
2. Создай функцию в `fixer/fixers/X.py` с тем же кодом через
   `@register("X.NN")`.
3. Локально импортируй предикат из валидатора, чтобы фиксер чинил
   ровно то, что находит проверка.
4. Не меняй текст и регистр (это правка контента, не формата).
5. Не трогай атрибуты со значением `None` — они наследуются от стиля.
6. Тесты: «правит ЯВНЫЕ атрибуты», «оставляет inherited (`None`)
   нетронутыми», «после fix проверка возвращает 0 нарушений».
7. Обнови `docs/checks-catalog.md` (раздел «Автофиксеры») и счётчик в README.

**При расширении парсера:**
1. Сначала фикстура. Положи минимальный `.docx` с искомым случаем в
   `tests/fixtures/synthetic/`.
2. Напиши падающий тест.
3. Только потом — код парсера.

**При работе с OOXML напрямую:**
- `python-docx` покрывает 70% случаев. Когда не хватает — `lxml`
  через `element.xml` и собственный XPath.
- Namespace map:
  `{"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}`
- Полезные референсы: ECMA-376,
  [python-docx docs](https://python-docx.readthedocs.io/).

**При работе с Streamlit-виджетами в builder_editor:**
- Используй стабильный per-сущность `id` как ключ (`{prefix}_{id}`),
  не позиционный индекс. Положи `setdefault("id", _new_block_id())` в
  начале функции рендера. Иначе после `pop`/`insert` Streamlit
  «приклеит» закэшированное значение виджета к чужой сущности по
  позиции.
- При клонировании (`_duplicate_block`, `_duplicate_section`)
  обнуляй id у копии — иначе оригинал и клон будут писать в один
  ключ виджета.
