"""单进程限流器：适用于当前单 worker 的个人实例。"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from app.core.config import get_settings


class FailureLimiter:
    """固定时间窗失败计数；进程重启后清空，不持久化用户凭据。"""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= window:
                events.popleft()
            return len(events) < limit

    def record(self, key: str, *, window: float) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= window:
                events.popleft()
            events.append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def client_ip(request: Request) -> str:
    """请求侧真实来源 IP。

    默认取 TCP 对端；置于反向代理后所有请求都来自 127.0.0.1，限流会退化成全局
    共享，此时把 ``trust_proxy_headers`` 打开，改读代理写入的 X-Forwarded-For
    第一跳（只有代理可信时才允许打开，否则客户端可以伪造成任意 IP）。
    """
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = request.headers.get("x-real-ip")
        if real_ip and real_ip.strip():
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


login_failures = FailureLimiter()
pairing_attempts = FailureLimiter()

__all__ = ["FailureLimiter", "client_ip", "login_failures", "pairing_attempts"]
