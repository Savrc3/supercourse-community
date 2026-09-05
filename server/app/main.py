"""超课表后端应用入口。"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.api.auth import router as auth_router
from app.api.importer import router as import_router
from app.api.media import router as media_router
from app.api.reminders import router as reminders_router
from app.api.sync import router as sync_router
from app.api.system import router as system_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.version import APP_VERSION
from app.modules.remind.engine import start_scheduler, stop_scheduler

API_PREFIX = "/api"
_logger = logging.getLogger("supercourse.request")


def configured_origins(settings: object) -> list[str]:
    raw = getattr(settings, "allowed_origins", "")
    origins = [item.strip() for item in str(raw).split(",") if item.strip()]
    if origins:
        return origins
    return [
        "https://localhost",
        "capacitor://localhost",
        "http://localhost",
        "http://localhost:5173",
    ]


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """在解析请求体前拒绝明显过大的请求。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw_length = request.headers.get("content-length")
        if raw_length:
            try:
                length = int(raw_length)
            except ValueError:
                return JSONResponse(
                    {"detail": {"code": "invalid_content_length", "message": "请求大小无效"}},
                    status_code=400,
                )
            if length > get_settings().max_request_bytes:
                return JSONResponse(
                    {"detail": {"code": "request_too_large", "message": "请求内容过大"}},
                    status_code=413,
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为本地开发、桌面端静态服务器之外的 API 响应补充基础安全头。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; object-src 'none'; "
            "frame-ancestors 'none'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self' https: http://localhost:* http://localhost:*; "
            "font-src 'self' data:; form-action 'self'",
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(self), geolocation=(), microphone=()"
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """给每个请求注入 request_id 并记录结构化日志。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-Id", str(uuid4()))
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Request-Id"] = request_id
        _logger.info(
            "request",
            extra={
                "fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 1),
                }
            },
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings().ensure_dirs()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="超课表 API",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if settings.env == "dev" else None,
        redoc_url="/redoc" if settings.env == "dev" else None,
        openapi_url="/openapi.json" if settings.env == "dev" else None,
    )
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured_origins(settings),
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(sync_router, prefix=API_PREFIX)
    app.include_router(import_router, prefix=API_PREFIX)
    app.include_router(media_router, prefix=API_PREFIX)
    app.include_router(reminders_router, prefix=API_PREFIX)
    return app


app = create_app()
