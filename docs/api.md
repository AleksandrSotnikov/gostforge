# REST API: руководство по использованию и деплою

> Полная спецификация endpoints — [phase-3-api-spec.md](phase-3-api-spec.md).
> Этот документ описывает практическое использование и production-деплой.

## 1. Установка и быстрый старт

```bash
pip install -e ".[api]"
gostforge serve
# API на http://127.0.0.1:8000
```

Проверка:

```bash
curl http://127.0.0.1:8000/health
# {"status": "ok", "version": "..."}
```

Swagger UI с интерактивной документацией: <http://127.0.0.1:8000/docs>.

## 2. Конфигурация через переменные окружения

| Переменная | Default | Назначение |
| --- | --- | --- |
| `GOSTFORGE_API_KEYS` | пусто (auth выключен) | Comma-separated API-ключи. Минимум 8 символов на ключ. |
| `GOSTFORGE_CORS_ORIGINS` | пусто (CORS запрещён) | Comma-separated origins для `Access-Control-Allow-Origin`. |
| `GOSTFORGE_MAX_UPLOAD_MB` | `25` | Лимит размера .docx в МБ. |

Генерация надёжного ключа:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 3. Аутентификация

Если `GOSTFORGE_API_KEYS` задан, все запросы кроме `/health`, `/docs`,
`/redoc` и `/openapi.json` обязаны прислать заголовок:

```
X-API-Key: <ваш ключ>
```

Невалидный или отсутствующий ключ → `401 {"error": "unauthorized"}`.

Поддерживается несколько ключей одновременно (для разных
потребителей — кафедра / LMS / CI):

```bash
export GOSTFORGE_API_KEYS="key-for-lms-aaa,key-for-ci-bbb,key-for-kafedra-ccc"
```

## 4. Примеры запросов

### 4.1. Проверить .docx

```bash
curl -X POST http://localhost:8000/check \
  -H "X-API-Key: $KEY" \
  -F file=@thesis.docx \
  -F profile_id=gost-7.32-2017
```

Ответ:

```json
{
  "profile_id": "gost-7.32-2017",
  "violations": [
    {
      "code": "F.01",
      "severity": "error",
      "message": "Левое поле 25 мм, требуется 30 мм",
      "location": "поля страницы",
      "suggestion": "Установите левое поле 30 мм",
      "details": {}
    }
  ],
  "summary": {"error": 3, "warning": 1, "info": 0}
}
```

### 4.2. Применить автофиксы

```bash
curl -X POST http://localhost:8000/fix \
  -H "X-API-Key: $KEY" \
  -F file=@thesis.docx \
  -o fixed.docx
```

Опционально — только конкретные коды:

```bash
curl -X POST http://localhost:8000/fix \
  -H "X-API-Key: $KEY" \
  -F file=@thesis.docx \
  -F only=T.08 -F only=T.10 \
  -o fixed.docx
```

### 4.3. Аннотировать комментариями Word

```bash
curl -X POST http://localhost:8000/annotate \
  -H "X-API-Key: $KEY" \
  -F file=@thesis.docx \
  -F style=comments \
  -o annotated.docx
```

### 4.4. Статистика документа

```bash
curl -X POST http://localhost:8000/stats \
  -H "X-API-Key: $KEY" \
  -F file=@thesis.docx
```

## 5. Деплой через Docker

В корне репозитория лежат `Dockerfile` и `docker-compose.yml`.

```bash
cp .env.example .env
# отредактируйте .env: задайте GOSTFORGE_API_KEYS и GOSTFORGE_CORS_ORIGINS
docker compose up -d
docker compose logs -f api
```

По умолчанию контейнер слушает только `127.0.0.1:8000` (для reverse-proxy).
Чтобы открыть наружу — установите `GOSTFORGE_BIND=0.0.0.0` в `.env`
**и обязательно поставьте перед сервисом TLS-прокси** (nginx / Caddy).

Образ:

* multi-stage build на `python:3.11-slim`,
* non-root user `gostforge`,
* embedded HEALTHCHECK через `/health`,
* лимит ресурсов 1 CPU / 512 МБ через `deploy.resources` в compose.

## 6. Деплой с reverse-proxy (nginx)

Минимальный конфиг nginx перед gostforge-api:

```nginx
server {
    listen 443 ssl http2;
    server_name normo.example.ru;

    ssl_certificate     /etc/letsencrypt/live/normo.example.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/normo.example.ru/privkey.pem;

    # Лимит размера тела — должен совпадать с GOSTFORGE_MAX_UPLOAD_MB.
    client_max_body_size 25M;

    # Простейший rate-limit: 5 req/s на IP.
    limit_req_zone $binary_remote_addr zone=gostforge:10m rate=5r/s;
    limit_req zone=gostforge burst=20 nodelay;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 7. Ограничения первой итерации

- Нет встроенного rate-limiting — используйте reverse-proxy.
- Нет персистентного хранения — каждый запрос обрабатывается в памяти.
- Нет WebSocket / streaming — нормоконтроль курсовой ≤ 1 секунды,
  синхронный ответ работает.
- API-key через env — для k8s/compose ОК; для динамической ротации
  ключей нужно расширить middleware (пока вне scope).

## 8. Интеграция с LMS

LMS (Moodle, Canvas, eLearning) могут вызывать API напрямую: студент
загружает работу, LMS делает `POST /check` в фоне, отображает
violations в интерфейсе курса. Для интеграции:

1. Прописать API URL и `X-API-Key` в настройках LMS.
2. На стороне LMS — handler, который маппит violations → UI
   (рендеринг таблицы / комментариев / автоблокировка сдачи на
   error-severity).
3. Опционально — выгрузка результата `/annotate` обратно студенту
   как часть фидбэка.
