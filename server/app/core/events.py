"""SSE 广播：写入成功后向所有在线设备广播新 rev（进程内 Queue）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import Request
from sse_starlette.sse import EventSourceResponse

# 每个订阅者一个 asyncio.Queue；真广播用 put，等价于同步 set。
_subscribers: set[asyncio.Queue[int]] = set()


def broadcast_rev(rev: int) -> None:
    """向所有在线订阅者广播一次 rev 变更。"""
    for queue in list(_subscribers):
        with suppress(asyncio.QueueFull):
            queue.put_nowait(rev)


async def _event_gen(request: Request) -> AsyncIterator[dict[str, str]]:
    queue: asyncio.Queue[int] = asyncio.Queue(maxsize=100)
    _subscribers.add(queue)
    try:
        # 立即发一个 hello，便于前端确认连接建立。
        yield {"event": "hello", "data": json.dumps({"rev": 0})}
        while True:
            if await request.is_disconnected():
                break
            try:
                rev = await asyncio.wait_for(queue.get(), timeout=20.0)
                yield {"event": "change", "data": json.dumps({"rev": rev})}
            except asyncio.TimeoutError:
                # 心跳，维持长连接。
                yield {"event": "heartbeat", "data": "ping"}
    finally:
        _subscribers.discard(queue)


async def sse_stream(request: Request) -> EventSourceResponse:
    """返回 SSE 响应。"""
    return EventSourceResponse(_event_gen(request), headers={"Cache-Control": "no-store"})


__all__ = ["broadcast_rev", "sse_stream"]
