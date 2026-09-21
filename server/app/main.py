"""课序后端应用入口。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.auth import router as auth_router
from app.api.importer import router as import_router
from app.api.media import router as media_router
from app.api.reminders import router as reminders_router
from app.api.sync import router as sync_router
from app.api.system import router as system_router
from app.core.config import get_settings
from app.core.events import bind_event_loop
from app.core.logging import setup_logging
from app.core.version import APP_VERSION
from app.modules.remind.engine import start_scheduler, stop_scheduler
from app.sync.tombstones import schedule_tombstone_purge

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
        "http://127.0.0.1:5173",
    ]


class RequestSizeLimitMiddleware:
    """请求体大小上限：Content-Length 快路径 + 边读边计数。

    只看 ``Content-Length`` 时，带 ``Transfer-Encoding: chunked`` 的请求可以绕过
    上限。这里先把请求体读到 ``max_request_bytes`` 以内（超出立即回 413），再把
    读到的内容回放给应用——若把计数放进 ``receive`` 里抛异常，FastAPI 的 JSON
    解析会把异常吞成 ``400 请求体解析失败``，错误码就不再是「太大」了。

    代价是请求体在进入应用前被完整读入内存（上限即 ``max_request_bytes``）。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = get_settings().max_request_bytes
        raw_length = Headers(scope=scope).get("content-length")
        if raw_length:
            try:
                length = int(raw_length)
            except ValueError:
                await _reject(send, 400, "invalid_content_length", "请求大小无效")
                return
            if length > limit:
                await _reject(send, 413, "request_too_large", "请求内容过大")
                return

        body = bytearray()
        disconnected = False
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
                break
            if message["type"] != "http.request":
                break
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await _reject(send, 413, "request_too_large", "请求内容过大")
                return
            if not message.get("more_body", False):
                break

        payload = bytes(body)
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": payload, "more_body": False}
            if disconnected:
                return {"type": "http.disconnect"}
            return await receive()

        await self.app(scope, replay_receive, send)


async def _reject(send: Send, status_code: int, code: str, message: str) -> None:
    body = json.dumps({"detail": {"code": code, "message": message}}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


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
            "connect-src 'self' https: http://localhost:* http://127.0.0.1:*; "
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
    # SSE 广播要从工作线程回到主 loop（同步端点在 AnyIO 线程池里执行）。
    bind_event_loop(asyncio.get_running_loop())
    start_scheduler()
    # 墓碑清理挂在同一个调度器上（每 6 小时一次）。
    schedule_tombstone_purge()
    try:
        yield
    finally:
        stop_scheduler()
        bind_event_loop(None)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="课序 API",
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
