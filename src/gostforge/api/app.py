# ruff: noqa: RUF001, RUF002, RUF003

"""FastAPI-приложение для gostforge.

Структура endpoints — см. docs/phase-3-api-spec.md. Главная фабрика
`create_app()` собирает приложение и регистрирует все маршруты;
объект `app` доступен на уровне модуля для прямого запуска
``uvicorn gostforge.api.app:app``.
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, Response
except ImportError as exc:  # pragma: no cover — extras [api] обязателен
    raise ImportError(
        'Установите gostforge[api] для REST API: pip install -e ".[api]"'
    ) from exc

from gostforge import __version__
from gostforge.profile import Profile, list_profiles, load_profile
from gostforge.validator import validate
from gostforge.validator.engine import registered_checks


# --- Конфигурация из env ----------------------------------------------------


_DEFAULT_MAX_UPLOAD_MB = 25
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _max_upload_bytes() -> int:
    """Лимит размера загружаемого файла в байтах из env.

    `GOSTFORGE_MAX_UPLOAD_MB` (целое, мегабайты). Невалидное значение
    или отсутствие переменной → default 25 МБ.
    """
    raw = os.environ.get("GOSTFORGE_MAX_UPLOAD_MB")
    if not raw:
        return _DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
    try:
        return max(1, int(raw)) * 1024 * 1024
    except ValueError:
        return _DEFAULT_MAX_UPLOAD_MB * 1024 * 1024


def _cors_origins() -> list[str]:
    """CORS-origins из env (comma-separated). Пустая строка → [] (запрет)."""
    raw = os.environ.get("GOSTFORGE_CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


# --- Утилиты обработки запроса ----------------------------------------------


async def _read_docx_upload(file: UploadFile) -> bytes:
    """Прочитать загруженный .docx с проверками формата и размера.

    Возвращает байты файла. Кидает HTTPException на:
      * отсутствующий файл (400),
      * не .docx по расширению (400),
      * превышение лимита размера (413).
    """
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="Файл не передан")
    suffix = Path(file.filename).suffix.lower()
    if suffix != ".docx":
        raise HTTPException(
            status_code=400,
            detail=f"Ожидался .docx, получено: {file.filename!r}",
        )
    data = await file.read()
    if len(data) > _max_upload_bytes():
        raise HTTPException(
            status_code=413,
            detail=f"Файл больше лимита ({_max_upload_bytes() // (1024 * 1024)} МБ)",
        )
    # zip-сигнатура .docx: PK\x03\x04
    if not data.startswith(b"PK"):
        raise HTTPException(status_code=400, detail="Файл не похож на .docx (нет PK-сигнатуры)")
    return data


def _load_profile_or_404(profile_id: str) -> Profile:
    """Загрузить профиль; вернуть HTTPException 404 если не существует."""
    try:
        return load_profile(profile_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=404, detail=f"Профиль {profile_id!r} не найден: {exc}"
        ) from exc


def _violation_to_dict(violation: Any) -> dict[str, Any]:
    """Сериализация Violation в JSON-совместимый dict для ответа /check."""
    return {
        "code": violation.check_code,
        "severity": violation.severity,
        "message": violation.message,
        "location": violation.location,
        "suggestion": violation.suggestion,
        "details": dict(violation.details),
    }


def _parse_uploaded_docx(data: bytes) -> Any:
    """Сохранить байты во временный файл, прогнать парсер, удалить файл."""
    from gostforge.parser import parse_docx

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        return parse_docx(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


# --- Фабрика приложения -----------------------------------------------------


def create_app() -> FastAPI:
    """Собрать FastAPI-приложение со всеми endpoints.

    Отдельная фабрика нужна для тестов (TestClient(create_app())) и
    для альтернативных конфигураций (например, под gunicorn).
    """
    app = FastAPI(
        title="gostforge",
        version=__version__,
        description=(
            "REST API нормоконтроля и автоисправления .docx по ГОСТу. "
            "Полная спецификация: docs/phase-3-api-spec.md."
        ),
    )

    origins = _cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness-проверка для мониторинга."""
        return {"status": "ok", "version": __version__}

    @app.get("/profiles")
    def get_profiles() -> list[dict[str, Any]]:
        """Список доступных профилей.

        Возвращает имя/id/версию/описание без полной выгрузки правил —
        для UI «выберите профиль» этого достаточно.
        """
        result: list[dict[str, Any]] = []
        for profile_id in list_profiles():
            try:
                p = load_profile(profile_id)
            except Exception:
                continue
            result.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "version": p.version,
                    "extends": p.extends,
                    "description": p.description,
                }
            )
        return result

    @app.get("/profiles/{profile_id}")
    def get_profile(profile_id: str) -> dict[str, Any]:
        """Полный JSON одного профиля (включая правила проверок)."""
        profile = _load_profile_or_404(profile_id)
        return profile.model_dump()

    @app.get("/checks")
    def get_checks() -> list[dict[str, str]]:
        """Список реализованных проверок с категорией.

        Категория — первая буква кода (F.01 → F).
        """
        return [
            {"code": code, "category": code.split(".")[0]}
            for code in registered_checks()
        ]

    @app.post("/check")
    async def post_check(
        file: UploadFile = File(...),
        profile_id: str = Form("gost-7.32-2017"),
    ) -> JSONResponse:
        """Прогнать нормоконтроль файла по выбранному профилю.

        Returns JSON-отчёт со списком violations и summary по severity.
        """
        data = await _read_docx_upload(file)
        profile = _load_profile_or_404(profile_id)
        try:
            document = _parse_uploaded_docx(data)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Не удалось распарсить .docx: {exc}"
            ) from exc
        violations = validate(document, profile)
        summary = Counter(v.severity for v in violations)
        return JSONResponse(
            {
                "profile_id": profile_id,
                "violations": [_violation_to_dict(v) for v in violations],
                "summary": {
                    "error": summary.get("error", 0),
                    "warning": summary.get("warning", 0),
                    "info": summary.get("info", 0),
                },
            }
        )

    @app.post("/fix")
    async def post_fix(
        file: UploadFile = File(...),
        only: list[str] = Form(default_factory=list),
        profile_id: str = Form("gost-7.32-2017"),
    ) -> Response:
        """Применить безопасные автофиксеры, вернуть исправленный .docx.

        `only` — опциональный список кодов проверок; если пуст,
        применяются все включённые в профиле фиксеры.
        """
        data = await _read_docx_upload(file)
        profile = _load_profile_or_404(profile_id)
        from gostforge.exporter import export_docx
        from gostforge.fixer import fix as run_fix

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as src:
            src.write(data)
            src_path = Path(src.name)
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as dst:
            dst_path = Path(dst.name)
        try:
            try:
                document = _parse_uploaded_docx(data)
                run_fix(document, profile, codes=list(only) if only else None)
                # source_docx=src_path сохранит реальные изображения.
                export_docx(document, profile, dst_path, source_docx=src_path)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(
                    status_code=500, detail=f"Не удалось применить фиксы: {exc}"
                ) from exc
            output_bytes = dst_path.read_bytes()
        finally:
            for p in (src_path, dst_path):
                try:
                    p.unlink()
                except OSError:
                    pass
        return Response(
            content=output_bytes,
            media_type=_DOCX_MIME,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="fixed-{file.filename or "document.docx"}"'
                ),
            },
        )

    @app.post("/annotate")
    async def post_annotate(
        file: UploadFile = File(...),
        profile_id: str = Form("gost-7.32-2017"),
        style: str = Form("comments"),
    ) -> Response:
        """Добавить комментарии Word с нарушениями, вернуть аннотированный .docx.

        `style` = `comments` (боковые выноски Word, по умолчанию) или
        `inline` (маркеры прямо в тексте).
        """
        if style not in ("comments", "inline"):
            raise HTTPException(
                status_code=400,
                detail=f"style должен быть 'comments' или 'inline', получено: {style!r}",
            )
        data = await _read_docx_upload(file)
        profile = _load_profile_or_404(profile_id)
        from gostforge.annotator import annotate_docx

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as src:
            src.write(data)
            src_path = Path(src.name)
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as dst:
            dst_path = Path(dst.name)
        try:
            try:
                # annotate_docx сам парсит, валидирует и аннотирует.
                annotate_docx(src_path, dst_path, profile, style=style)  # type: ignore[arg-type]
            except Exception as exc:
                raise HTTPException(
                    status_code=500, detail=f"Не удалось аннотировать: {exc}"
                ) from exc
            output_bytes = dst_path.read_bytes()
        finally:
            for p in (src_path, dst_path):
                try:
                    p.unlink()
                except OSError:
                    pass
        return Response(
            content=output_bytes,
            media_type=_DOCX_MIME,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="annotated-{file.filename or "document.docx"}"'
                ),
            },
        )

    @app.post("/stats")
    async def post_stats(file: UploadFile = File(...)) -> JSONResponse:
        """Структурная статистика документа (число параграфов, разделов и т.п.)."""
        data = await _read_docx_upload(file)
        try:
            document = _parse_uploaded_docx(data)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Не удалось распарсить .docx: {exc}"
            ) from exc
        from gostforge.stats import compute_stats

        stats = compute_stats(document)
        # DocumentStats — dataclass: разворачиваем в dict через __dict__.
        return JSONResponse(stats.__dict__)

    return app


# Готовый объект для uvicorn:
#     uvicorn gostforge.api.app:app
app = create_app()
