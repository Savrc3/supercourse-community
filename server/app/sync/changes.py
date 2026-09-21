"""增量拉取：游标分页 + 全量回退。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.journal import current_rev, now_iso
from app.sync.registry import REGISTRY, get_spec
from app.sync.tombstones import tombstone_floor


def _fetch_changes(
    session: Session,
    since: int,
    limit: int,
) -> list[tuple[str, dict[str, Any]]]:
    changes: list[tuple[str, dict[str, Any]]] = []
    for entity, spec in REGISTRY.items():
        rows = session.execute(
            select(spec.model).where(spec.model.rev > since).order_by(spec.model.rev).limit(limit)
        ).scalars()
        for row in rows:
            data: dict[str, Any] = {
                "id": row.id,
                "rev": row.rev,
                "updated_at": row.updated_at,
                "deleted_at": row.deleted_at,
            }
            for field in spec.writable_fields():
                data[field] = getattr(row, field, None)
            changes.append((entity, data))
    return changes


def build_changes(
    session: Session,
    *,
    since: int,
    limit: int = 500,
    full: bool = False,
) -> dict[str, Any]:
    """构造 /api/sync/changes 响应。

    full=True 时走全量快照（bootstrap 复用）。游标低于墓碑水位线时（说明它可能
    错过了已被清掉的删除记录）自动升级为全量快照，客户端据此重建本地库。
    """
    latest = current_rev(session)
    if not full and since < tombstone_floor(session):
        full = True
    if full:
        snapshot: dict[str, list[dict[str, Any]]] = {}
        for entity, spec in REGISTRY.items():
            rows = session.execute(select(spec.model).order_by(spec.model.rev)).scalars()
            snapshot[entity] = []
            for row in rows:
                data: dict[str, Any] = {
                    "id": row.id,
                    "rev": row.rev,
                    "updated_at": row.updated_at,
                    "deleted_at": row.deleted_at,
                }
                for field in spec.writable_fields():
                    data[field] = getattr(row, field, None)
                snapshot[entity].append(data)
        return {
            "changes": _flatten_snapshot(snapshot),
            "next_cursor": latest,
            "latest_rev": latest,
            "server_time": now_iso(),
            "full": True,
            "snapshot": snapshot,
        }

    changes = sorted(_fetch_changes(session, since, limit), key=lambda item: item[1]["rev"])
    if len(changes) > limit:
        changes = changes[:limit]
    next_cursor = changes[-1][1]["rev"] if changes else latest
    return {
        "changes": changes,
        "next_cursor": next_cursor,
        "latest_rev": latest,
        "server_time": now_iso(),
    }


def _flatten_snapshot(
    snapshot: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for entity, rows in snapshot.items():
        for row in rows:
            out.append((entity, row))
    out.sort(key=lambda item: item[1].get("rev", 0))
    return out


def build_bootstrap(session: Session) -> dict[str, Any]:
    """/api/bootstrap：首次全量。"""
    return build_changes(session, since=0, full=True)


__all__ = ["build_changes", "build_bootstrap", "get_spec"]
