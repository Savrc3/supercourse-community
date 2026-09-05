"""唯一写入入口：字段级 LWW 合并 + 幂等 + 冲突箱。

技术方案 §5：客户端一律 POST /api/sync/push，服务端逐条处理——
* op_id 已见 → 返回原结果（幂等，重试安全）；
* 字段白名单 + 校验，非法 op 回明确错误码；
* base_rev == 当前 rev → 直接应用；
* base_rev 过期 → 字段级 LWW 合并，败方整行快照写 conflict。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.journal import clamp_updated_at, next_rev, now_iso
from app.models import Conflict, OpLog, Setting
from app.sync.registry import EntityName, get_spec


class SyncError(Exception):
    """同步错误，code 供前端按稳定字符串处理。"""

    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass
class OpResult:
    """单条 op 的处理结果。"""

    op_id: str
    status: str  # applied | merged | conflict | rejected
    new_rev: int | None = None
    server_row: dict[str, Any] | None = None
    conflict_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"op_id": self.op_id, "status": self.status}
        if self.new_rev is not None:
            out["new_rev"] = self.new_rev
        if self.server_row is not None:
            out["server_row"] = self.server_row
        if self.conflict_id is not None:
            out["conflict_id"] = self.conflict_id
        if self.error is not None:
            out["error"] = {"code": self.error}
        return out


def _row_to_dict(row: Any, spec: Any) -> dict[str, Any]:
    """把 ORM 行转成客户端可读的行快照（含通用列 + 白名单字段）。"""
    data: dict[str, Any] = {
        "id": row.id,
        "rev": row.rev,
        "updated_at": row.updated_at,
        "deleted_at": row.deleted_at,
    }
    for field in spec.writable_fields():
        data[field] = getattr(row, field, None)
    return data


def _find_row(session: Session, spec: Any, row_id: str) -> Any | None:
    return session.get(spec.model, row_id)


def _apply_merge(
    session: Session,
    spec: Any,
    row: Any,
    base_rev: int,
    updates: dict[str, Any],
    device_id: str,
    op_id: str,
) -> OpResult:
    """base_rev 过期时的字段级 LWW 合并。

    对每个客户端改动字段：若该字段在服务端自 base_rev 后也变过
    （即当前 rev != base_rev 且该列值已非旧快照）→ 记为冲突字段，
    取 updated_at 新者为胜（相同则服务端胜）；败方整行快照写 conflict。
    """
    server_ts = row.updated_at
    client_ts = updates.get("updated_at")

    # 提取冲突字段：客户端改动的字段，若服务端当前值与客户端要写入的值不同，
    # 说明两端对该字段都写了不同内容 → 记冲突。
    conflict_fields: list[str] = [
        field
        for field, value in updates.items()
        if field not in ("rev", "updated_at", "deleted_at") and getattr(row, field, None) != value
    ]

    # 胜负判定：冲突字段取 updated_at 新者胜（相同则服务端胜）
    client_wins = False
    if conflict_fields and client_ts and server_ts:
        try:
            client_wins = client_ts > server_ts
        except TypeError:
            client_wins = False

    # 逐字段应用（冲突字段按胜负决定是否采纳客户端值）
    for field, value in updates.items():
        if field in ("rev", "updated_at"):
            continue
        if field in conflict_fields and not client_wins:
            continue
        setattr(row, field, value)

    row.rev = next_rev(session)
    row.updated_at = clamp_updated_at(client_ts or now_iso())

    conflict_id: str | None = None
    if conflict_fields:
        from app.core.journal import now_iso as _now

        conflict_id = f"conf-{row.id}-{row.rev}"
        session.add(
            Conflict(
                id=conflict_id,
                entity=spec.table,
                row_id=row.id,
                device_id=device_id,
                base_rev=base_rev,
                server_row=json.dumps(_row_to_dict(row, spec), ensure_ascii=False),
                local_row=json.dumps(updates, ensure_ascii=False),
                winner="server" if not client_wins else "client",
                created_at=_now(),
            )
        )

    return OpResult(
        op_id=op_id,
        status="merged" if conflict_fields else "applied",
        new_rev=row.rev,
        server_row=_row_to_dict(row, spec),
        conflict_id=conflict_id,
    )


def apply_op(
    session: Session,
    *,
    op_id: str,
    entity: EntityName,
    row_id: str,
    set_fields: dict[str, Any],
    base_rev: int,
    device_id: str,
    op_ts: str | None = None,
    deleted: bool | None = None,
) -> OpResult:
    """应用单条 op。所有分支都在同一事务里，由调用方统一 commit。

    ``deleted`` 是服务端生成 ``deleted_at`` 的软删除/恢复操作；客户端
    不得直接写入服务端时间字段。
    """
    spec = get_spec(entity)
    if spec is None:
        return OpResult(op_id, "rejected", error="unknown_entity")

    # 幂等：op_id 已见 → 返回原结果（删除/恢复也不能绕过这里）。
    existing = session.get(OpLog, op_id)
    if existing is not None:
        return OpResult(
            op_id,
            existing.status or "rejected",
            new_rev=existing.applied_rev,
            error=existing.error,
        )

    if deleted is not None:
        if set_fields:
            return OpResult(op_id, "rejected", error="delete_with_set")
        row = _find_row(session, spec, row_id)
        if row is None:
            return OpResult(op_id, "rejected", error="not_found")
        if base_rev == 0:
            base_rev = row.rev
        row.deleted_at = now_iso() if deleted else None
        row.rev = next_rev(session)
        row.updated_at = clamp_updated_at(op_ts or now_iso())
        session.add(
            OpLog(
                client_op_id=op_id,
                device_id=device_id,
                entity=entity,
                row_id=row_id,
                status="applied",
                applied_rev=row.rev,
                created_at=now_iso(),
            )
        )
        return OpResult(op_id, "applied", new_rev=row.rev, server_row=_row_to_dict(row, spec))

    # 白名单校验：未知字段拒绝
    unknown = [f for f in set_fields if not spec.is_writable(f)]
    if unknown:
        return OpResult(op_id, "rejected", error="unknown_field")
    if entity == "todo" and "status" in set_fields and str(set_fields["status"]) not in {"0", "1"}:
        return OpResult(op_id, "rejected", error="invalid_status")

    row = _find_row(session, spec, row_id)
    if entity == "setting":
        # setting 的业务唯一键是 key；不同设备可能为同一 key 生成不同本地 id。
        key = set_fields.get("key")
        if isinstance(key, str) and key:
            row = session.scalar(select(Setting).where(Setting.key == key)) or row
    if row is None:
        # 新建
        row = spec.model(id=row_id)
        row.rev = next_rev(session)
        row.updated_at = clamp_updated_at(op_ts)
        row.deleted_at = None
        for field, value in set_fields.items():
            setattr(row, field, value)
        # todo/media 缺 created_at 用现在补
        if hasattr(row, "created_at") and row.created_at is None:
            row.created_at = now_iso()
        session.add(row)
        session.flush()
    else:
        if base_rev == 0:
            base_rev = row.rev
        if base_rev == row.rev:
            # 直接应用
            for field, value in set_fields.items():
                setattr(row, field, value)
            row.rev = next_rev(session)
            row.updated_at = clamp_updated_at(op_ts)
        else:
            # 字段级 LWW 合并
            result = _apply_merge(
                session,
                spec,
                row,
                base_rev,
                set_fields,
                device_id,
                op_id,
            )
            session.add(
                OpLog(
                    client_op_id=op_id,
                    device_id=device_id,
                    entity=entity,
                    row_id=row_id,
                    status=result.status,
                    applied_rev=result.new_rev,
                    created_at=now_iso(),
                )
            )
            return result

    session.add(
        OpLog(
            client_op_id=op_id,
            device_id=device_id,
            entity=entity,
            row_id=row_id,
            status="applied",
            applied_rev=row.rev,
            created_at=now_iso(),
        )
    )
    return OpResult(op_id, "applied", new_rev=row.rev, server_row=_row_to_dict(row, spec))


def push_ops(
    session: Session,
    ops: list[dict[str, Any]],
    device_id: str,
) -> list[OpResult]:
    """批量推送。同事务内逐条应用，任何 op 失败不中断其它。"""
    results: list[OpResult] = []
    for raw in ops:
        op_id = str(raw.get("op_id", ""))
        entity = str(raw.get("entity", ""))
        row_id = str(raw.get("id", ""))
        set_fields = raw.get("set", {})
        base_rev = int(raw.get("base_rev", 0) or 0)
        op_ts = raw.get("updated_at")
        deleted_raw = raw.get("deleted")
        deleted: bool | None = deleted_raw if isinstance(deleted_raw, bool) else None
        if not op_id or not entity or not row_id:
            results.append(OpResult(op_id, "rejected", error="malformed_op"))
            continue
        if not isinstance(set_fields, dict):
            results.append(OpResult(op_id, "rejected", error="malformed_op"))
            continue
        if "deleted" in raw and not isinstance(deleted_raw, bool):
            results.append(OpResult(op_id, "rejected", error="malformed_op"))
            continue
        result = apply_op(
            session,
            op_id=op_id,
            entity=entity,
            row_id=row_id,
            set_fields=set_fields,
            base_rev=base_rev,
            device_id=device_id,
            op_ts=op_ts,
            deleted=deleted,
        )
        results.append(result)
    return results


__all__ = [
    "SyncError",
    "OpResult",
    "apply_op",
    "push_ops",
    "_row_to_dict",
]
