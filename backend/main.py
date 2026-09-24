"""App factory.  `create_app(settings, repo)` lets tests inject a temp DB."""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, get_settings
from .db.base import TaskRepository
from .errors import AppError
from .routes import router

log = logging.getLogger("task_api")


def build_repo(s: Settings) ->TaskRepository:
    if s.db_backend == "mongo":
        from .db.mongo_repo import MongoTaskRepository
        return MongoTaskRepository(s.mongo_uri, s.mongo_db, s.mongo_use_transactions, s.max_tasks_per_user)

def _envelope(request: Request, status: int, code: str, message: str,
              details: list | None = None, headers: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or [],
                      "request_id": getattr(request.state, "request_id", None)}}
    return JSONResponse(body, status_code=status, headers=headers)

def create_app(setting:Settings | None = None, repo: TaskRepository | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Task API", version="1.0",
                  description="CRUD API that an LLM agent calls through tools.")
    app.state.repo = repo or build_repo(settings)
    app.state.repo.init()
    
    @app.middleware("http")
    async def request_id_middleware(request:Request,call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response
    
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return _envelope(request, exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)              # Pydantic request validation → 422
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]),
                    "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return _envelope(request, 422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)              # 404 unknown route, 405 …
    async def _http(request: Request, exc: StarletteHTTPException):
        return _envelope(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)                           # last resort – never leak internals
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error request_id=%s", getattr(request.state, "request_id", None))
        return _envelope(request, 500, "internal_error", "Unexpected server error")
    
    app.include_router(router)
    return app

app = None


def get_app() ->FastAPI:
    return create_app()