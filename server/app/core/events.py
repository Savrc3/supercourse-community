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

# 主事件循环：同步端点跑在 AnyIO 工作线程里，跨线程操作 asyncio.Queue
# 是未定义行为，必须回到这个 loop 上再 put。
_main_loop: asyncio.AbstractEventLoop | None = None


def bind_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """登记服务主事件循环（应用启动时调用）。"""
    global _main_loop
    _main_loop = loop


def _publish(rev: int) -> None:
    for queue in list(_subscribers):
        with suppress(asyncio.QueueFull):
            queue.put_nowait(rev)


def broadcast_rev(rev: int) -> None:
    """向所有在线订阅者广播一次 rev 变更。

    同时支持从事件循环内（async 端点）与工作线程（``def`` 端点，如
    ``/sync/push``）调用；线程安全由 ``call_soon_threadsafe`` 保证。
    """
    loop = _main_loop
    if loop is None or loop.is_closed():
        # 没有登记 loop（例如测试直接调用）：退化为同线程 put。
        _publish(rev)
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        _publish(rev)
    else:
        loop.call_soon_threadsafe(_publish, rev)


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


__all__ = ["bind_event_loop", "broadcast_rev", "sse_stream"]
