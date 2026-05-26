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
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, Response
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.types import ASGIApp
except ImportError as exc:  # pragma: no cover — extras [api] обязателен
    raise ImportError('Установите gostforge[api] для REST API: pip install -e ".[api]"') from exc

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


def _api_keys() -> set[str]:
    """API-ключи из env GOSTFORGE_API_KEYS (comma-separated).

    Пустая строка / отсутствие переменной → set() (auth выключен —
    все запросы анонимны). Минимальная длина ключа 8 символов; короче
    игнорируется как опечатка.
    """
    raw = os.environ.get("GOSTFORGE_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip() and len(k.strip()) >= 8}


# Пути, которые НЕ требуют API-key даже когда auth включён —
# liveness-проверки доступны мониторингу без секретов.
_AUTH_BYPASS_PATHS: frozenset[str] = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Простейшая аутентификация по заголовку X-API-Key.

    Поведение:
    * Если env `GOSTFORGE_API_KEYS` не задан / пустой — middleware
      пропускает все запросы (режим разработки).
    * Если ключи заданы — каждый запрос (кроме `_AUTH_BYPASS_PATHS`)
      должен прислать заголовок `X-API-Key: <значение>`.
    * Невалидный ключ → 401 + JSON `{detail, error}`.

    Сравнение строкой через `==` приемлемо для small set ключей.
    Для большого числа ключей и серьёзной защиты от timing-атак
    нужно перейти на hmac.compare_digest.
    """

    def __init__(self, app: ASGIApp, *, allowed_keys: set[str]) -> None:
        super().__init__(app)
        self._allowed = allowed_keys

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if not self._allowed:
            return await call_next(request)
        if request.url.path in _AUTH_BYPASS_PATHS:
            return await call_next(request)
        provided = request.headers.get("x-api-key", "")
        if provided and provided in self._allowed:
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Неверный или отсутствует X-API-Key",
                "error": "unauthorized",
            },
        )


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


def _comment_to_dict(comment: Any) -> dict[str, Any]:
    """Сериализация Comment в JSON-dict для ответа /comments."""
    return {
        "id": comment.id,
        "submission_id": comment.submission_id,
        "author": comment.author,
        "role": comment.role,
        "body": comment.body,
        "resolved": comment.resolved,
        "created_at": comment.created_at,
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
            allow_headers=["*", "X-API-Key"],
        )

    keys = _api_keys()
    app.add_middleware(APIKeyMiddleware, allowed_keys=keys)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness-проверка для мониторинга."""
        return {"status": "ok", "version": __version__}

    @app.get("/profiles")
    def get_profiles() -> list[dict[str, Any]]:
        """Список доступных профилей (builtin + установленные локально).

        Возвращает имя/id/версию/описание/is_custom. Полная выгрузка
        правил — через GET /profiles/{id}.
        """
        from gostforge.profile import is_custom_profile

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
                    "is_custom": is_custom_profile(p.id),
                }
            )
        return result

    @app.get("/profiles/{profile_id}")
    def get_profile(profile_id: str) -> dict[str, Any]:
        """Полный JSON одного профиля (включая правила проверок)."""
        profile = _load_profile_or_404(profile_id)
        return profile.model_dump()

    @app.post("/profiles")
    async def install_profile_endpoint(
        file: UploadFile = File(...),
        overwrite: bool = Form(False),
    ) -> dict[str, Any]:
        """Установить кафедральный YAML-профиль в локальный реестр.

        Принимает multipart/form-data с file=*.yaml (YAML профиля).
        Парсит и валидирует через Pydantic; при ошибке схемы возвращает
        400. При попытке установить duplicate без overwrite=true — 409.
        """
        if not file or not file.filename:
            raise HTTPException(status_code=400, detail="Файл не передан")
        if not file.filename.lower().endswith((".yaml", ".yml")):
            raise HTTPException(
                status_code=400,
                detail=f"Ожидался .yaml/.yml, получено: {file.filename!r}",
            )
        data = await file.read()
        if len(data) > 1024 * 1024:  # 1 МБ — профили обычно <50 КБ
            raise HTTPException(status_code=413, detail="YAML слишком большой (>1 МБ)")
        try:
            yaml_content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"YAML должен быть UTF-8: {exc}") from exc

        from gostforge.db import get_connection
        from gostforge.db.custom_profiles import install_profile

        try:
            with get_connection() as conn:
                rec = install_profile(
                    conn,
                    yaml_content=yaml_content,
                    source=f"upload:{file.filename}",
                    overwrite=overwrite,
                )
        except ValueError as exc:
            msg = str(exc)
            status = 409 if "уже установлен" in msg else 400
            raise HTTPException(status_code=status, detail=msg) from exc

        return {
            "id": rec.id,
            "profile_id": rec.profile_id,
            "name": rec.name,
            "version": rec.version,
            "source": rec.source,
            "installed_at": rec.installed_at,
        }

    @app.delete("/profiles/{profile_id}")
    def uninstall_profile_endpoint(profile_id: str) -> dict[str, bool]:
        """Удалить custom-профиль из реестра.

        Builtin-профили (gost-7.32-2017 и т.п.) удалить нельзя — они
        в каталоге пакета, не в БД. Если профиль не в БД, 404.
        """
        from gostforge.db import get_connection
        from gostforge.db.custom_profiles import uninstall_profile

        with get_connection() as conn:
            removed = uninstall_profile(conn, profile_id)
        if not removed:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Профиль {profile_id!r} не установлен в локальный реестр "
                    "(builtin-профили удалять нельзя)."
                ),
            )
        return {"deleted": True}

    @app.get("/checks")
    def get_checks() -> list[dict[str, str]]:
        """Список реализованных проверок с категорией.

        Категория — первая буква кода (F.01 → F).
        """
        return [{"code": code, "category": code.split(".")[0]} for code in registered_checks()]

    @app.post("/check")
    async def post_check(
        file: UploadFile = File(...),
        profile_id: str = Form("gost-7.32-2017"),
        record: bool = Form(True),
    ) -> JSONResponse:
        """Прогнать нормоконтроль файла по выбранному профилю.

        Returns JSON-отчёт со списком violations и summary по severity.
        Если record=True (по умолчанию) — submission сохраняется в
        локальную БД истории, в ответе возвращается submission_id.
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

        submission_id: int | None = None
        if record:
            try:
                from gostforge.db import get_connection, record_submission

                with get_connection() as conn:
                    submission_id = record_submission(
                        conn,
                        filename=file.filename or "uploaded.docx",
                        profile_id=profile_id,
                        violations=violations,
                    )
            except Exception:  # pragma: no cover - не валим API на БД
                submission_id = None

        return JSONResponse(
            {
                "profile_id": profile_id,
                "violations": [_violation_to_dict(v) for v in violations],
                "summary": {
                    "error": summary.get("error", 0),
                    "warning": summary.get("warning", 0),
                    "info": summary.get("info", 0),
                },
                "submission_id": submission_id,
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

    @app.get("/submissions")
    def get_submissions(limit: int = 20, filename: str | None = None) -> list[dict[str, Any]]:
        """История проверок из локальной БД.

        Лимит до 200 (защита от тяжёлых выгрузок). По filename — точное
        совпадение (для трекинга прогресса над одной работой).
        Возвращает только метаданные + summary; за деталями обращайтесь
        к /submissions/{id}.
        """
        from gostforge.db import get_connection, list_submissions

        capped = min(max(int(limit), 1), 200)
        with get_connection() as conn:
            items = list_submissions(conn, limit=capped, filename=filename)
        return [
            {
                "id": s.id,
                "filename": s.filename,
                "profile_id": s.profile_id,
                "created_at": s.created_at,
                "error_count": s.error_count,
                "warning_count": s.warning_count,
                "info_count": s.info_count,
            }
            for s in items
        ]

    @app.get("/submissions/{submission_id}")
    def get_submission_endpoint(submission_id: int) -> dict[str, Any]:
        """Детали одного submission со списком всех violations.

        Также возвращает ``unresolved_comments`` — счётчик открытых
        комментариев, чтобы UI мог нарисовать бейдж «1 незакрытый
        вопрос от руководителя» без второго запроса.
        """
        from gostforge.db import (
            count_unresolved_comments,
            get_connection,
            get_submission,
        )

        with get_connection() as conn:
            sub = get_submission(conn, submission_id)
            if sub is None:
                raise HTTPException(
                    status_code=404, detail=f"Submission #{submission_id} не найден"
                )
            unresolved = count_unresolved_comments(conn, submission_id)
        return {
            "id": sub.id,
            "filename": sub.filename,
            "profile_id": sub.profile_id,
            "created_at": sub.created_at,
            "summary": {
                "error": sub.error_count,
                "warning": sub.warning_count,
                "info": sub.info_count,
            },
            "unresolved_comments": unresolved,
            "violations": [
                {
                    "id": v.id,
                    "code": v.code,
                    "severity": v.severity,
                    "message": v.message,
                    "location": v.location,
                    "suggestion": v.suggestion,
                }
                for v in sub.violations
            ],
        }

    @app.delete("/submissions/{submission_id}")
    def delete_submission_endpoint(submission_id: int) -> dict[str, bool]:
        """Удалить submission (и все его violations через CASCADE)."""
        from gostforge.db import get_connection
        from gostforge.db.submissions import delete_submission

        with get_connection() as conn:
            deleted = delete_submission(conn, submission_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Submission #{submission_id} не найден")
        return {"deleted": True}

    # --- Comments (Фаза 3, миграция v3) ------------------------------------

    @app.get("/submissions/{submission_id}/comments")
    def list_comments_endpoint(
        submission_id: int, include_resolved: bool = True
    ) -> list[dict[str, Any]]:
        """Список комментариев к submission в хронологическом порядке.

        Параметр ``include_resolved=false`` — скрыть закрытые
        (для панели «что осталось обсудить»).
        """
        from gostforge.db import get_connection, list_comments

        with get_connection() as conn:
            items = list_comments(
                conn,
                submission_id=submission_id,
                include_resolved=include_resolved,
            )
        return [_comment_to_dict(c) for c in items]

    @app.post("/submissions/{submission_id}/comments")
    def add_comment_endpoint(submission_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Добавить комментарий к submission.

        Body JSON: ``{"body": "...", "author": "...", "role": "supervisor"}``.
        Поля ``author`` и ``role`` опциональны (default ``""`` и
        ``anonymous`` соответственно). Возвращает созданный комментарий.
        """
        from gostforge.db import add_comment, get_connection

        body = payload.get("body", "")
        author = payload.get("author", "") or ""
        role = payload.get("role", "anonymous") or "anonymous"
        if not isinstance(body, str) or not body.strip():
            raise HTTPException(
                status_code=400, detail="Поле 'body' обязательно и не должно быть пустым"
            )
        try:
            with get_connection() as conn:
                comment = add_comment(
                    conn,
                    submission_id=submission_id,
                    body=body,
                    author=str(author),
                    role=str(role),
                )
        except ValueError as exc:
            msg = str(exc)
            status = 404 if "не существует" in msg else 400
            raise HTTPException(status_code=status, detail=msg) from exc
        return _comment_to_dict(comment)

    @app.patch("/comments/{comment_id}/resolve")
    def resolve_comment_endpoint(
        comment_id: int, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Пометить комментарий как resolved (или снять отметку).

        Body JSON опционален: ``{"resolved": true|false}``. По умолчанию
        ``resolved=true`` (закрыть). Чтобы снять отметку — явно
        ``{"resolved": false}``.
        """
        from gostforge.db import get_comment, get_connection, resolve_comment

        resolved = True
        if payload is not None and "resolved" in payload:
            resolved = bool(payload["resolved"])
        with get_connection() as conn:
            ok = resolve_comment(conn, comment_id, resolved=resolved)
            if not ok:
                raise HTTPException(status_code=404, detail=f"Комментарий #{comment_id} не найден")
            updated = get_comment(conn, comment_id)
        assert updated is not None  # сразу после resolve_comment — должен быть
        return _comment_to_dict(updated)

    @app.delete("/comments/{comment_id}")
    def delete_comment_endpoint(comment_id: int) -> dict[str, bool]:
        """Удалить комментарий."""
        from gostforge.db import delete_comment, get_connection

        with get_connection() as conn:
            deleted = delete_comment(conn, comment_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Комментарий #{comment_id} не найден")
        return {"deleted": True}

    return app


# Готовый объект для uvicorn:
#     uvicorn gostforge.api.app:app
app = create_app()
