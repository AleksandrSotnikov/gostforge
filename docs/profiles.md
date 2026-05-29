# Система профилей

## Что такое профиль

Профиль — YAML-файл, описывающий три аспекта одного стандарта оформления:

1. **Стили** — параметры вёрстки (шрифты, поля, интервалы, форматы подписей).
   Типизированы через Pydantic-классы: `BodyTextProfile`,
   `HeadingStyleProfile` (×4), `CaptionStyleProfile`,
   `TableStyleProfile`, `FigureStyleProfile`, `ListStyleProfile`.
2. **Шаблон секций** — типовая структура PageSection с колонтитулами.
3. **Правила проверок** — какие из 119 проверок включены и с какими
   параметрами.

Один профиль — один стандарт. Профиль `gost-7.32-2017` — базовый, профиль `mguu-2025` — кафедра МГУ управления, унаследованный от базового с переопределениями.

## Расположение

- **Встроенные:** `profiles/` в репозитории (`gost-7.32-2017`,
  `gost-r-2.105-2019`, `example-department`).
- **Пользовательские (рекомендуется):** локальный реестр в SQLite-БД
  `~/.gostforge/gostforge.db`. Установка через
  `gostforge profiles install file.yaml` или REST `POST /profiles`.
  См. раздел «Установка кафедрального профиля» ниже и
  [database.md](database.md).
- При совпадении ID пользовательский профиль из БД переопределяет
  встроенный — кафедра может «уточнить» базовый ГОСТ под себя.

## Установка кафедрального профиля

Любой кафедральный YAML можно установить в локальный реестр одной
командой — после этого профиль доступен всем потребителям (CLI, REST
API, конструктор):

```bash
# Установить из локального файла.
gostforge profiles install /path/to/kafedra.yaml

# С перезаписью существующего:
gostforge profiles install kafedra.yaml --overwrite

# Посмотреть установленные с маркерами builtin/custom.
gostforge profiles list

# Удалить.
gostforge profiles uninstall kafedra-prog-2026
```

То же через REST:

```bash
# Установка.
curl -X POST http://localhost:8000/profiles \
  -H "X-API-Key: $KEY" \
  -F file=@kafedra.yaml

# С overwrite.
curl -X POST http://localhost:8000/profiles \
  -H "X-API-Key: $KEY" \
  -F file=@kafedra.yaml -F overwrite=true

# Удаление.
curl -X DELETE -H "X-API-Key: $KEY" \
  http://localhost:8000/profiles/kafedra-prog-2026
```

Перед записью YAML валидируется через Pydantic-схему. Битый формат
или отсутствие обязательных полей (`id`, `name`) → понятная ошибка
до сохранения в БД.

Распространение между студентами: одной кафедральной командой
выложить YAML на GitHub / сайт, студенты делают
`gostforge profiles install URL.yaml` (после `curl -O URL`) и
пишут проверки с этим профилем. Это убирает необходимость править
исходники gostforge или копировать YAML по виртуалкам.

## Минимальный пример

```yaml
id: gost-7.32-2017
name: ГОСТ 7.32-2017 (базовый)
version: "1.0"
based_on:
  - "ГОСТ 7.32-2017"
  - "ГОСТ Р 2.105-2019"
  - "ГОСТ Р 7.0.100-2018"
effective_from: "2018-07-01"
description: |
  Базовый профиль для отчётов о научно-исследовательской работе,
  курсовых и дипломных работ.

styles:
  page:
    size: A4
    margins_mm: {top: 20, right: 15, bottom: 20, left: 30}
  body:
    font: Times New Roman
    size_pt: 14
    line_spacing: 1.5
    first_line_indent_cm: 1.25
    alignment: justify
    hyphenation: false
    # По ГОСТу — 0 pt между абзацами. Разделение достигается красной
    # строкой + полуторным межстрочным. Если кафедра хочет 6/8 pt —
    # переопределяется.
    space_before_pt: 0
    space_after_pt: 0
  heading_1:
    font: Times New Roman
    size_pt: 14
    bold: true
    uppercase: true
    color: auto          # 'auto' = чёрный; иначе hex без # (например, '000080')
    alignment: center
    spacing_before_pt: 18
    spacing_after_pt: 12
    page_break_before: true
  heading_2:
    bold: true
    alignment: left
    first_line_indent_cm: 1.25
    spacing_before_pt: 12
    spacing_after_pt: 6
  figure:
    alignment: center    # рисунок по центру страницы
    caption:
      alignment: center  # подпись «Рисунок 1 — ...» по центру
      position: below
      format: "Рисунок {num} — {title}"
  table:
    border_style: single  # 'single' / 'double' / 'dashed' / 'none'
    border_size: 4        # 1/8 pt; 4 = 0.5 pt
    border_color: auto
    header_bold: true
    caption:
      alignment: left
      position: above     # подпись над таблицей по ГОСТу
      format: "Таблица {num} — {title}"
  lists:
    bullet_char: "–"            # тире по ГОСТ Р 7.32-2017
    ordered_format: "{n})"      # «1)», «2)», ...
    left_indent_cm: 1.75        # «Отступ текста» (куда переносится строка)
    hanging_indent_cm: 0.5      # выступ маркера: >0 — маркер левее текста
    marker_suffix: tab          # символ после маркера: tab | space | nothing
  # ... (см. полный пример в profiles/gost-7.32-2017.yaml)

sections_template:
  - name: Титульный лист
    type: title
    page_numbering: {visible: false}
  - name: Основная часть
    type: main
    page_numbering: {visible: true, format: arabic, start_at: 3}
    footer:
      default: {center: "{page}"}
  # ... 

checks:
  F.01: {enabled: true}
  F.04: {enabled: true, position: bottom_center}
  T.01: {enabled: true, font: "Times New Roman"}
  T.02: {enabled: true, body_size: 14, caption_size: 12}
  # ...
```

## Наследование

```yaml
id: my-department-2026
name: Кафедра информатики (2026)
extends: gost-7.32-2017
version: "1.0"

# Переопределяем только то, что отличается
styles:
  body:
    size_pt: 12  # на нашей кафедре 12, а не 14

checks:
  T.02: {enabled: true, body_size: 12}  # синхронно с body
  R.11: {enabled: true, min_sources: 30}  # требование кафедры
  X.99: {enabled: true}  # кастомная проверка, добавлена плагином кафедры
```

При загрузке профиль `my-department-2026` сливается с родительским по полям (deep merge), и итоговая конфигурация используется единообразно.

## Версионирование

Каждый профиль имеет `version`. Когда внесены breaking changes — версия инкрементируется. Проекты студентов запоминают `profile_id + version` на момент создания: работа 2025 года проверяется по той версии профиля, под которую писалась.

При выходе нового ГОСТа создаётся новый профиль (например, `gost-7.32-2027`) с собственным `effective_from`. Старый профиль не удаляется — остаётся для проверки старых работ.

## Как создать свой профиль кафедры (пошагово)

Самый частый сценарий: у кафедры есть своя методичка с отличиями от
базового ГОСТ 7.32-2017. Профиль создаётся за 10 минут.

### 1. Скопируйте шаблон

```bash
cp profiles/example-department.yaml profiles/my-department.yaml
```

Имя файла станет ID профиля. После того как файл готов, его можно
сразу проверять через `gostforge check work.docx -p my-department`.

### 2. Заполните header

```yaml
id: my-department      # должно совпадать с именем файла
name: Кафедра ИКТ МГУ (методичка 2026)
version: "1.0"         # увеличивайте при значимых правках
extends: gost-7.32-2017 # наследуем от базового — переопределяем только различия
description: |
  Краткое описание: для каких работ применим (курсовые / дипломы / ВКР),
  ссылка на методичку.
```

### 3. Переопределите только то, что отличается

Благодаря deep-merge всё, что не указано — берётся из родителя. Не
нужно копировать весь `styles:` и `checks:` — только различия.

Типовые правки кафедр:

| Что меняют | Где править |
| --- | --- |
| Кегль основного текста | `styles.body.size_pt` + параллельно `checks.T.02.params.body_size` |
| Отступ красной строки | `styles.body.first_line_indent_cm` + `checks.T.04.params.first_line_indent_cm` |
| Межстрочный интервал | `styles.body.line_spacing` + `checks.T.03.params.line_spacing` |
| Шрифт | `styles.body.font` + `checks.T.01.params.font` |
| Стартовая страница нумерации | `checks.F.06.params.start_value` |
| Список обязательных разделов | `checks.S.01.params.required_headings` |
| Ослабить web-источники R.04 | `checks.R.04.params.require_url_marker_for_web: false` |
| Минимум источников | `checks.R.11.params.min_sources` (в Фазе 2) |

**Правило согласованности**: параметры `styles.*` и `checks.*.params.*`
должны быть синхронны. Если на кафедре кегль 12, нужно поменять оба
места — иначе экспортёр будет писать 12, а проверка T.02 ждать 14.

### 4. Отключите неприменимые проверки

Если у кафедры свои нестандартные правила, мешающие проверке —
отключите её через `enabled: false`. Например, кафедра разрешает
точку в заголовке:

```yaml
checks:
  H.08: {enabled: false}
```

### 5. Проверьте профиль на синтетическом документе

```bash
# Загрузка профиля без ошибок
gostforge profiles show my-department

# Проверка тестового файла
gostforge check sample.docx -p my-department
```

Если в выводе CLI появилась строка «Не реализованы: …», значит профиль
ссылается на проверки, которых пока нет в коде — это не ошибка, просто
предупреждение.

### 6. Поделитесь профилем

Профиль — обычный YAML-файл, можно положить в git кафедры или отправить
по почте. Студенты копируют его в `~/.gostforge/profiles/` (Linux/Mac)
или `%APPDATA%\gostforge\profiles\` (Windows).

## Структура файла (полная спецификация)

См. JSON Schema в `src/gostforge/profile/schema.py` (Pydantic-модели).

## Валидация профилей

При загрузке профиль проходит проверку: все обязательные поля заполнены, типы корректны, ссылки на проверки указывают на существующие коды, наследование не циклично.

CLI: `gostforge profiles validate path/to/profile.yaml`.

## Маркетплейс профилей (фаза 4)

В далёкой перспективе — публичный реестр профилей разных ВУЗов и кафедр. Профиль кафедры публикуется как ссылка на git-репозиторий, подключается командой `gostforge profiles install github.com/.../profile.yaml`.

Пока — обмен файлами вручную.
