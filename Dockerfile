# gostforge REST API — production-ready image.
#
# Сборка:
#   docker build -t gostforge:latest .
#
# Запуск:
#   docker run -p 8000:8000 \
#     -e GOSTFORGE_API_KEYS=my-secret-key-123 \
#     -e GOSTFORGE_CORS_ORIGINS=https://lms.example.com \
#     gostforge:latest
#
# Multi-stage:
#   1. builder  — компиляция wheel и установка зависимостей в /opt/venv.
#   2. runtime  — slim-образ с готовым venv и кодом, без build-toolchain.

# --- Stage 1: builder -------------------------------------------------------

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# build-essential нужен только если установятся wheels-у-которых-нет-binary
# (на python:3.11-slim для python-docx/lxml колёса есть). Оставляем для подстраховки.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Сначала только pyproject — лучше кэшируется на пересборках.
COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/
COPY profiles/ ./profiles/

RUN pip install --no-cache-dir ".[api]"

# --- Stage 2: runtime -------------------------------------------------------

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    GOSTFORGE_MAX_UPLOAD_MB=25

# Создаём непривилегированного пользователя.
RUN groupadd --system gostforge && \
    useradd --system --gid gostforge --no-create-home --shell /usr/sbin/nologin gostforge

# Копируем venv и профили из builder-стейджа.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/profiles /app/profiles
COPY --from=builder /build/src /app/src
COPY --from=builder /build/pyproject.toml /app/pyproject.toml
COPY --from=builder /build/README.md /app/README.md

WORKDIR /app
USER gostforge

EXPOSE 8000

# HEALTHCHECK — k8s/compose могут проверять /health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "gostforge.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
