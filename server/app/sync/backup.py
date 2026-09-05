"""export / restore：全量备份与恢复（保留原 id、逐条校验）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.journal import current_rev, next_rev
from app.sync.registry import REGISTRY


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


def restore_all(session: Session, data: dict[str, Any]) -> dict[str, int]:
    """按 op 落库，保留原 id；逐条校验白名单字段。"""
    rows = data.get("rows", {})
    restored = 0
    # 先清空业务表，避免旧数据残留（恢复语义 = 全量覆盖）。
    for spec in REGISTRY.values():
        session.execute(spec.model.__table__.delete())
    session.flush()

    for entity, records in rows.items():
        entity_spec = REGISTRY.get(entity)
        if entity_spec is None:
            continue
        for rec in records:
            row_id = str(rec.get("id", ""))
            if not row_id:
                continue
            row = entity_spec.model(id=row_id)
            row.rev = rec.get("rev", 0) or next_rev(session)
            row.updated_at = rec.get("updated_at", "")
            row.deleted_at = rec.get("deleted_at")
            for field in entity_spec.writable_fields():
                if field in rec:
                    setattr(row, field, rec[field])
            session.add(row)
            restored += 1
    session.flush()
    return {"restored": restored}


__all__ = ["export_all", "restore_all"]
