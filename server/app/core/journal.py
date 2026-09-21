"""全局 rev 取号器与统一写路径。

技术方案 §5：服务端每次写入从 ``seq`` 取一个全局单调 ``rev``；
写路径统一「取 rev → 更新行 → 提交」，保证所有可同步行共享一条时间线。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import Seq


def now_iso() -> str:
    """UTC ISO8601（截断到秒，与服务端时间戳格式一致）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    """把 ISO8601 时间戳解析为带时区的 datetime；不可解析返回 None。

    用于比较客户端与服务端的 ``updated_at``：字符串比较在不同时区偏移
    下会给出错误结果（``+08:00`` 与 ``Z`` 混用）。
    """
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def latest_iso(*values: str | None) -> str:
    """返回若干个 ISO8601 时间戳中最新者；全部不可用时返回当前时间。

    用于「行最后写入时间」：合并后不应把行的 ``updated_at`` 回退到旧值，
    否则后续 LWW 判断会用到过期时间。
    """
    best: datetime | None = None
    best_raw: str | None = None
    for raw in values:
        parsed = parse_iso(raw)
        if parsed is None:
            continue
        if best is None or parsed > best:
            best = parsed
            best_raw = raw
    return best_raw or now_iso()


def _ensure_seq_row(session: Session) -> None:
    """确保 ``seq`` 单行存在（并发首写也不会撞 ``uq_seq_k``）。"""
    session.execute(
        sqlite_insert(Seq).values(k=1, v=0).on_conflict_do_nothing(index_elements=["k"])
    )


def next_rev(session: Session) -> int:
    """取下一个全局 rev（单调 +1），并持久化到单行 ``seq``。

    并发安全：自增在 SQL 层完成（``UPDATE ... SET v = v + 1``），两个并发
    事务不会读到同一个旧值——Python 里 read-modify-write 会，表现为多台
    设备同时同步后出现重复 rev，增量拉取按 ``rev > since`` 过滤时永久漏行。
    """
    _ensure_seq_row(session)
    session.execute(update(Seq).where(Seq.k == 1).values(v=Seq.v + 1))
    value = session.scalar(select(Seq.v).where(Seq.k == 1))
    return int(value or 1)


def bump_rev_floor(session: Session, rev: int) -> None:
    """把全局 seq 抬到至少 ``rev``。

    备份恢复 / 导入回滚会把旧时间线的 rev 写回库；若不抬升 seq，后续
    ``next_rev`` 会重新分配相同的 rev，破坏「全局单调时间线」前提。
    """
    if rev <= 0:
        return
    _ensure_seq_row(session)
    session.execute(update(Seq).where(Seq.k == 1).values(v=func.max(Seq.v, rev)))


def current_rev(session: Session) -> int:
    """最近一次已分配的 rev（未写入任何行时返回 0）。"""
    value = session.scalar(select(Seq.v).where(Seq.k == 1))
    return int(value or 0)


def clamp_updated_at(updated_at: str | None, server_now: str | None = None) -> str:
    """把客户端打戳的 ``updated_at`` 钳制到服务端时间。

    §5.6 时钟：客户端用本地时钟+offset 打戳，服务端把未来超过 60 秒的
    ``updated_at`` 钳制为服务端当前时间，防止某台设备污染排序。
    """
    if not updated_at:
        return now_iso()
    server = server_now or now_iso()
    ts = parse_iso(updated_at)
    ref = parse_iso(server)
    if ts is None or ref is None:
        return server
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
    "bump_rev_floor",
    "clamp_updated_at",
    "current_rev",
    "latest_iso",
    "next_rev",
    "now_iso",
    "parse_iso",
    "stamp_new_row",
]
