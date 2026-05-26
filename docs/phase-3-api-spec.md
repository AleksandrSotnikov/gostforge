# Фаза 3 — REST API: спецификация

> **Статус:** ТЗ + первая итерация.
> **Опциональная зависимость:** `pip install -e ".[api]"`.

## 1. Цель

Открыть функционал gostforge (check / fix / annotate / profiles /
checks) через HTTP — для интеграций с LMS (Moodle, eLearning),
кафедральных CI-пайплайнов, веб-форм проверки и любых третьих
сервисов, которым не подходит CLI или Streamlit-UI.

API минимальный, без аутентификации (на первой итерации), без
персистентного хранения. Один запрос = один документ.

## 2. Endpoints

| Метод | Путь | Назначение | Тело запроса | Ответ |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | Liveness-проверка. | — | `{"status": "ok", "version": "..."}` |
| `GET` | `/profiles` | Список доступных профилей. | — | `[{"id": "...", "name": "...", ...}, ...]` |
| `GET` | `/profiles/{profile_id}` | Полный JSON одного профиля. | — | объект Profile |
| `GET` | `/checks` | Список реализованных проверок. | — | `[{"code": "F.01", "category": "F"}, ...]` |
| `POST` | `/check` | Прогнать нормоконтроль. | `multipart`: `file`=.docx, `profile_id`=str (опц.) | JSON-отчёт о нарушениях |
| `POST` | `/fix` | Применить автофиксы. | `multipart`: `file`=.docx, `only`=str[] (опц.) | Исправленный `.docx` (binary) |
| `POST` | `/annotate` | Добавить комментарии Word. | `multipart`: `file`=.docx, `style`=`comments`/`inline` | Аннотированный `.docx` (binary) |
| `POST` | `/stats` | Структурная статистика. | `multipart`: `file`=.docx | JSON статистики |

Все POST-endpoints принимают `multipart/form-data` с обязательным
полем `file` (.docx). `profile_id` опционален — по умолчанию
`gost-7.32-2017`.

## 3. Схема ответа `/check`

```json
{
  "profile_id": "gost-7.32-2017",
  "violations": [
    {
      "code": "F.01",
      "severity": "error",
      "message": "Левое поле 25 мм, требуется 30 мм",
      "location": "поля страницы",
      "suggestion": "Установите левое поле 30 мм"
    }
  ],
  "summary": {"error": 3, "warning": 1, "info": 0}
}
```

Коды ошибок HTTP:

- `200` — успех.
- `400` — невалидный input (нет файла, не .docx).
- `404` — неизвестный `profile_id`.
- `413` — файл слишком большой (по умолчанию 25 МБ).
- `422` — Pydantic-ошибка валидации запроса.
- `500` — внутренняя ошибка.

## 4. Запуск

```bash
pip install -e ".[api]"
gostforge serve --host 0.0.0.0 --port 8000
```

`gostforge serve` — обёртка над `uvicorn gostforge.api.app:app`.
`--reload` включает hot-reload для разработки.

## 5. Не-цели первой итерации

- Аутентификация / авторизация (предполагается reverse-proxy).
- Rate limiting (внешним слоем).
- WebSocket / streaming.
- Персистентное хранение: каждый запрос обрабатывается в памяти.
- CORS — настраивается env-переменной `GOSTFORGE_CORS_ORIGINS`.

**Размер файла** — по умолчанию 25 МБ, env-переменная
`GOSTFORGE_MAX_UPLOAD_MB`.

## 6. Тесты

Каждый endpoint покрыт ≥ 2 тестами через `fastapi.testclient`:

- Happy path: валидный .docx → 200 + правильное тело.
- Error path: нет файла / неизвестный профиль / битый docx.

## 7. План коммитов

1. `feat(api): структура + /health + /profiles + /checks` — фундамент.
2. `feat(api): POST /check с обработкой multipart .docx`.
3. `feat(api): POST /fix + /annotate + /stats`.
4. `feat(cli): команда gostforge serve`.
5. `docs: docs/api.md + README + roadmap`.
