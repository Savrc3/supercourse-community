"""全局 rev 取号器与统一写路径。

技术方案 §5：服务端每次写入从 ``seq`` 取一个全局单调 ``rev``；
写路径统一「取 rev → 更新行 → 提交」，保证所有可同步行共享一条时间线。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Seq


def now_iso() -> str:
    """UTC ISO8601（截断到秒，与服务端时间戳格式一致）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_rev(session: Session) -> int:
    """取下一个全局 rev（单调 +1），并持久化到单行 ``seq``。

    并发安全：由 SQLite 单写锁 + ``busy_timeout`` 保证不重复分配。
    """
    seq = session.get(Seq, 1)
    if seq is None:
        seq = Seq(k=1, v=0)
        session.add(seq)
        session.flush()
    seq.v += 1
    session.flush()
    return seq.v


def current_rev(session: Session) -> int:
    """最近一次已分配的 rev（未写入任何行时返回 0）。"""
    seq = session.get(Seq, 1)
    return seq.v if seq is not None else 0


def clamp_updated_at(updated_at: str | None, server_now: str | None = None) -> str:
    """把客户端打戳的 ``updated_at`` 钳制到服务端时间。

    §5.6 时钟：客户端用本地时钟+offset 打戳，服务端把未来超过 60 秒的
    ``updated_at`` 钳制为服务端当前时间，防止某台设备污染排序。
    """
    if not updated_at:
        return now_iso()
    server = server_now or now_iso()
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        ref = datetime.fromisoformat(server.replace("Z", "+00:00"))
    except ValueError:
        return server
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    if (ts - ref).total_seconds() > 60:
        return server
    return updated_at


def stamp_new_row(
    row: Any,
    session: Session,
    *,
    updated_at: str | None = None,
) -> None:
    """为新建行填充 rev/updated_at/deleted_at 通用列。调用方随后 flush。"""
    row.rev = next_rev(session)
    row.updated_at = clamp_updated_at(updated_at)


__all__ = [
    "now_iso",
    "next_rev",
    "current_rev",
    "clamp_updated_at",
    "stamp_new_row",
]
