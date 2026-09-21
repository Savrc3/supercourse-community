"""墓碑清理与「游标过旧」的全量回退。

软删行（``deleted_at`` 非空）要留一段时间给离线设备同步；超过
``tombstone_days`` 后清理，并把**墓碑水位线**抬到这些行里最大的 ``rev``。
设备游标低于水位线，说明它可能已经错过被清掉的删除记录，此时
``/api/sync/changes`` 必须回全量快照（``full: true``）而不是增量——否则那批
删除会永久丢失，客户端留下一批「幽灵行」。

水位线存在 ``meta`` 表（键 ``tombstone_floor``），与 ``seq`` 的全局 rev 同一
时间轴，因此可以直接和客户端游标比较。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine, session_scope
from app.core.journal import parse_iso
from app.core.media_rules import media_file_path
from app.models import Meta
from app.sync.registry import REGISTRY

FLOOR_KEY = "tombstone_floor"

# 先删子行再删父行：外键约束在，父行仍被存活行引用时删不掉（这类行会被跳过）。
PURGE_ORDER: tuple[str, ...] = (
    "attachment",
    "todo",
    "media",
    "course_slot",
    "timetable_override",
    "setting",
    "course",
    "lesson_period",
    "term",
)


def tombstone_floor(session: Session) -> int:
    """当前墓碑水位线（无记录返回 0）。"""
    row = session.get(Meta, FLOOR_KEY)
    if row is None:
        return 0
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return 0


def set_tombstone_floor(session: Session, rev: int) -> None:
    """把水位线抬到 ``rev``（只增不减）。"""
    if rev <= 0:
        return
    value = str(max(rev, tombstone_floor(session)))
    row = session.get(Meta, FLOOR_KEY)
    if row is None:
        session.add(Meta(key=FLOOR_KEY, value=value))
    else:
        row.value = value
    session.flush()


def _purge_media_file(media_id: str, ext: object) -> None:
    """删掉 media 行时一并删除磁盘文件（尽力而为，失败不影响清理）。"""
    path = media_file_path(get_settings().media_dir, media_id, ext)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def purge_tombstones(
    session: Session,
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """删除过期墓碑并推进水位线；返回 {entity: 删除行数}。

    ``days <= 0`` 表示关闭清理（保留所有墓碑，水位线不动）。
    """
    window = get_settings().tombstone_days if days is None else days
    if window <= 0:
        return {}
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=window)
    cutoff_iso = cutoff.astimezone(timezone.utc).isoformat(timespec="seconds")
    purged: dict[str, int] = {}
    max_rev = 0
    for entity in PURGE_ORDER:
        spec = REGISTRY.get(entity)
        if spec is None or not hasattr(spec.model, "deleted_at"):
            continue
        model = spec.model
        candidates = (
            session.execute(
                select(model).where(model.deleted_at.is_not(None), model.deleted_at < cutoff_iso)
            )
            .scalars()
            .all()
        )
        removed = 0
        for row in candidates:
            # 时间戳可能带 'Z' 或非 UTC 偏移，字符串比较只当粗筛，这里按解析值定夺。
            deleted_at = parse_iso(row.deleted_at)
            if deleted_at is None or deleted_at > cutoff:
                continue
            try:
                with session.begin_nested():
                    session.delete(row)
            except IntegrityError:
                # 仍被其它行引用（外键）：留着，水位线也不越过它。
                continue
            removed += 1
            max_rev = max(max_rev, int(row.rev or 0))
            if entity == "media":
                _purge_media_file(row.id, getattr(row, "ext", None))
        if removed:
            purged[entity] = removed
    if max_rev:
        set_tombstone_floor(session, max_rev)
    session.flush()
    return purged


def purge_tombstones_job() -> int:
    """调度器入口：独立事务里跑一次清理，返回删除行数。"""
    with session_scope(get_engine()) as session:
        return sum(purge_tombstones(session).values())


def schedule_tombstone_purge() -> bool:
    """把清理挂到已有调度器上（没有调度器时跳过，例如测试环境）。"""
    from app.modules.remind.engine import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        return False
    scheduler.add_job(
        purge_tombstones_job,
        "interval",
        hours=6,
        id="tombstone-purge",
        replace_existing=True,
        # 启动 30 秒后先跑一次，之后每 6 小时一次。
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    return True


__all__ = [
    "FLOOR_KEY",
    "PURGE_ORDER",
    "purge_tombstones",
    "purge_tombstones_job",
    "schedule_tombstone_purge",
    "set_tombstone_floor",
    "tombstone_floor",
]
