"""单进程限流器：适用于当前单 worker 的个人实例。"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


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


login_failures = FailureLimiter()

__all__ = ["FailureLimiter", "login_failures"]
