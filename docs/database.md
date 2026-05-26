# Локальная БД gostforge

> SQLite, stdlib, ноль внешних зависимостей. Используется для истории
> проверок, в перспективе — для маркетплейса профилей и комментариев.

## 1. Где лежит БД

По умолчанию: `~/.gostforge/gostforge.db`.

Переопределить можно env-переменной `GOSTFORGE_DB_PATH` — удобно для:

* тестов (изоляция в tmp-каталоге);
* Docker (volume на отдельный диск);
* мульти-пользовательских установок (одна БД на нескольких юзеров).

```bash
export GOSTFORGE_DB_PATH=/var/lib/gostforge/db.sqlite
gostforge check thesis.docx
```

## 2. Автоматическая инициализация

Никаких `gostforge db init` или `alembic upgrade head` запускать
не нужно. При первом обращении к БД (например, при первом
`gostforge check`) каталог и файл создаются автоматически, все
миграции применяются по `schema_version`-таблице. Подход
идемпотентный — повторный запуск — noop.

Текущая схема:

```
schema_version (version INTEGER PRIMARY KEY)
submissions (id, filename, profile_id, created_at, error_count,
             warning_count, info_count)
violations (id, submission_id FK→submissions, code, severity,
            message, location, suggestion)
```

`ON DELETE CASCADE` на `violations.submission_id` — удаление
submission уносит свои violations. Включено через
`PRAGMA foreign_keys = ON`. Журнал — `WAL` для лучшей параллельности.

## 3. Что записывается автоматически

| Действие | Что попадает в БД |
| --- | --- |
| `gostforge check file.docx` | Submission с filename + все violations |
| `gostforge check ./folder/` | По одной записи на каждый .docx |
| `POST /check` (REST API) | То же, что CLI |

Отключить запись:

* CLI: флаг `--no-record`.
* API: form-параметр `record=false`.

## 4. Просмотр истории

### CLI

```bash
# Последние 20 проверок.
gostforge history

# Последние N.
gostforge history --limit 50

# Только конкретный файл — трекинг прогресса.
gostforge history --filename thesis.docx

# Подробности одного submission.
gostforge history --id 42
```

### REST API

```bash
# Список (метаданные + summary).
curl -H "X-API-Key: $KEY" http://localhost:8000/submissions

# С фильтром по имени файла.
curl -H "X-API-Key: $KEY" \
  "http://localhost:8000/submissions?filename=thesis.docx&limit=10"

# Детали с violations.
curl -H "X-API-Key: $KEY" http://localhost:8000/submissions/42

# Удалить запись.
curl -X DELETE -H "X-API-Key: $KEY" http://localhost:8000/submissions/42
```

## 5. Persistence в Docker

По умолчанию контейнер `gostforge-api` хранит БД в файловой системе
контейнера — она пропадает при `docker compose down -v`.

Чтобы сохранить историю между перезапусками, монтируйте volume.
В `docker-compose.yml` раскомментируйте:

```yaml
services:
  api:
    # ...
    volumes:
      - gostforge-data:/var/lib/gostforge
    environment:
      GOSTFORGE_DB_PATH: /var/lib/gostforge/gostforge.db

volumes:
  gostforge-data:
```

UI-сервис может использовать тот же volume или свой собственный.

## 6. Резервное копирование

SQLite — это один файл. Простейший бэкап:

```bash
sqlite3 ~/.gostforge/gostforge.db ".backup '/backup/gostforge-$(date +%F).db'"
```

Атомарный — sqlite3 `.backup` использует online-backup API, не блокирует
писателей.

## 7. Сброс / миграция

```bash
# Удалить базу и начать с нуля.
rm ~/.gostforge/gostforge.db*  # *.db, *.db-wal, *.db-shm

# Следующий запуск пересоздаст всё.
gostforge check file.docx
```

## 8. Программный доступ из Python

```python
from gostforge.db import get_connection, list_submissions, get_submission

with get_connection() as conn:
    # Последние 5 проверок.
    for s in list_submissions(conn, limit=5):
        print(f"#{s.id} {s.filename}: {s.error_count} ошибок")

    # Детали по id.
    sub = get_submission(conn, 42)
    if sub:
        for v in sub.violations:
            print(f"  {v.severity}: {v.code} — {v.message}")
```

## 9. Что планируется добавить

Следующие миграции расширят БД под новые фичи:

* **v2 — пользовательские профили**: таблица `custom_profiles` (id,
  name, version, yaml_content, source_url, installed_at). Маркетплейс
  профилей кафедр будет хранить здесь установленные YAML-ы.
* **v3 — комментарии руководителя**: таблицы `users`, `comments`,
  `review_threads` для совместной работы студент ↔ руководитель.

Каждая миграция добавляется только append-only в `migrations.py`;
существующие записи никогда не редактируются.
