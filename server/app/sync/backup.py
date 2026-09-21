"""export / restore：全量备份与恢复（保留原 id、逐条校验）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.journal import bump_rev_floor, current_rev, next_rev, now_iso
from app.sync.registry import REGISTRY
from app.sync.validation import RESTORE_ORDER, validate_restore_row


def export_all(session: Session) -> dict[str, Any]:
    """导出全量数据（不含令牌散列等基础设施敏感文档）。"""
    rows: dict[str, list[dict[str, Any]]] = {}
    for entity, spec in REGISTRY.items():
        records = session.execute(select(spec.model).order_by(spec.model.rev)).scalars()
        rows[entity] = []
        for row in records:
            rec: dict[str, Any] = {
                "id": row.id,
                "rev": row.rev,
                "updated_at": row.updated_at,
                "deleted_at": row.deleted_at,
            }
            for field in spec.writable_fields():
                rec[field] = getattr(row, field, None)
            rows[entity].append(rec)
    return {"schema_version": "1", "rows": rows, "latest_rev": current_rev(session)}


def _ordered_entities(rows: dict[str, Any]) -> list[str]:
    """按依赖顺序遍历：父行先落库，手写备份的顺序不影响外键。"""
    known = [entity for entity in RESTORE_ORDER if entity in rows]
    extra = [entity for entity in rows if entity not in RESTORE_ORDER]
    return known + extra


def _payload_floor(rows: dict[str, Any], latest_rev: Any) -> int:
    """备份里出现过的最大 rev（含 ``latest_rev`` 声明）。"""
    floor = latest_rev if isinstance(latest_rev, int) and latest_rev > 0 else 0
    for records in rows.values():
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rev = rec.get("rev")
            if isinstance(rev, int) and rev > floor:
                floor = rev
    return floor


def restore_all(session: Session, data: dict[str, Any]) -> dict[str, int]:
    """按 op 落库，保留原 id；逐条校验白名单字段。

    rev 不复用备份里的值：恢复 = 全量覆盖，重新取号才能让「已经拿着旧游标
    的其他设备」在增量拉取里看到这批数据；同时把 seq 抬到备份时间线之上，
    保证后续取号不与该时间线撞号（撞号会让 ``rev > since`` 过滤永久漏行）。
    非法行跳过并计数，不再让端点以 500 收场。
    """
    rows = data.get("rows", {})
    if not isinstance(rows, dict):
        rows = {}
    # 先清空业务表，避免旧数据残留（恢复语义 = 全量覆盖）。
    for spec in REGISTRY.values():
        session.execute(spec.model.__table__.delete())
    session.flush()

    bump_rev_floor(session, max(_payload_floor(rows, data.get("latest_rev")), current_rev(session)))

    restored = 0
    skipped = 0
    seen: dict[str, set[str]] = {}
    for entity in _ordered_entities(rows):
        entity_spec = REGISTRY.get(entity)
        records = rows.get(entity)
        if entity_spec is None or not isinstance(records, list):
            continue
        ids = seen.setdefault(entity, set())
        for rec in records:
            if not isinstance(rec, dict):
                skipped += 1
                continue
            row_id = str(rec.get("id", ""))
            if not row_id or row_id in ids:
                skipped += 1
                continue
            fields = {field: rec[field] for field in entity_spec.writable_fields() if field in rec}
            if validate_restore_row(session, entity, entity_spec.model, row_id, fields):
                skipped += 1
                continue
            row = entity_spec.model(id=row_id)
            row.rev = next_rev(session)
            row.updated_at = rec.get("updated_at") or now_iso()
            row.deleted_at = rec.get("deleted_at")
            for field, value in fields.items():
                setattr(row, field, value)
            if hasattr(row, "created_at") and not getattr(row, "created_at", None):
                row.created_at = now_iso()
            session.add(row)
            ids.add(row_id)
            restored += 1
        # 按实体分组落库：模型之间没有 relationship，flush 顺序不做依赖排序，
        # 同一次 flush 里子行可能先于父行插入 → 外键报错。父实体整组先落库。
        session.flush()
    return {"restored": restored, "skipped": skipped}


__all__ = ["export_all", "restore_all"]
