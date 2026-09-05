"""同步相关端点：配对 / 同步 / 冲突 / 设备 / SSE。"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    CurrentDeviceId,
    authenticate_token,
    bearer,
    create_pairing,
    exchange_pairing,
)
from app.core.db import get_session
from app.core.events import broadcast_rev, sse_stream
from app.core.journal import clamp_updated_at, current_rev, next_rev, now_iso
from app.models import Conflict, Device
from app.modules.remind.engine import CONFIG_KEY, load_config, refresh_daily_summary_schedule
from app.sync.backup import export_all, restore_all
from app.sync.changes import build_bootstrap, build_changes
from app.sync.push import push_ops
from app.sync.registry import get_spec

router = APIRouter(tags=["sync"])

Db = Annotated[Session, Depends(get_session)]


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "message": message},
    )


@router.post("/pairing/start")
def pairing_start(
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """已登录设备生成一次性配对码（5 分钟过期）。"""
    code, ttl = create_pairing(session, device_id)
    return {"code": code, "expires_in": ttl}


@router.post("/pairing/exchange")
def pairing_exchange(
    payload: dict[str, Any],
    session: Db,
) -> dict[str, Any]:
    """新设备用一次性码换长效令牌（仅此一次明文返回 token）。"""
    code = str(payload.get("code", ""))
    name = str(payload.get("name", ""))
    platform = str(payload.get("platform", ""))
    if not code or not name:
        raise _bad_request("invalid_request", "缺少 code 或 name")
    device_id, token = exchange_pairing(session, code=code, name=name, platform=platform)
    return {"device_id": device_id, "token": token}


@router.get("/bootstrap")
def bootstrap(
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """首次全量拉取。"""
    data = build_bootstrap(session)
    data["schema_version"] = "1"
    return data


@router.get("/sync/changes")
def changes(
    device_id: CurrentDeviceId,
    session: Db,
    since: int = 0,
    limit: int = 500,
) -> dict[str, Any]:
    """增量拉取，配合 SSE 使用。"""
    limit = max(1, min(limit, 2000))
    return build_changes(session, since=since, limit=limit)


@router.post("/sync/push")
def sync_push(
    payload: dict[str, Any],
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """唯一写入入口：幂等 + 字段级 LWW。"""
    ops = payload.get("ops", [])
    if not isinstance(ops, list):
        raise _bad_request("invalid_request", "ops 必须是数组")
    results = push_ops(session, ops, device_id)
    latest = current_rev(session)
    if any(
        result.status in ("applied", "merged")
        and str(raw.get("entity")) == "setting"
        and isinstance(raw.get("set"), dict)
        and raw["set"].get("key") == CONFIG_KEY
        for raw, result in zip(ops, results, strict=False)
    ):
        refresh_daily_summary_schedule(load_config(session))
    if results and any(r.status in ("applied", "merged") for r in results):
        broadcast_rev(latest)
    return {"results": [r.to_dict() for r in results], "latest_rev": latest}


@router.get("/events")
async def events(
    request: Request,
    session: Db,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
    token: str | None = Query(default=None),
) -> Any:
    """SSE 实时通知，20s 心跳。"""
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_token", "message": "缺少 Bearer token"},
        )
    authenticate_token(raw_token, session)
    return await sse_stream(request)


@router.get("/export")
def export(
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """全量备份下载（含图片引用清单，不含 token）。"""
    return export_all(session)


@router.post("/restore")
def restore(
    payload: dict[str, Any],
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """换机恢复：校验后保留原 id 落库。"""
    result = restore_all(session, payload)
    broadcast_rev(current_rev(session))
    return result


@router.get("/conflicts")
def list_conflicts(
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """冲突箱列表（未解决项）。"""
    rows = session.execute(select(Conflict).where(Conflict.resolved_at.is_(None))).scalars()
    return {"conflicts": [_conflict_json(r) for r in rows]}


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: str,
    payload: dict[str, Any],
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """解决冲突：choice = server | local | manual。"""
    choice = str(payload.get("choice", ""))
    row = session.get(Conflict, conflict_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "冲突不存在"},
        )
    if choice not in {"server", "local"}:
        raise _bad_request("invalid_choice", "只能选择保留服务端或本地版本")
    if choice == "local":
        spec = get_spec(row.entity or "")
        target = session.get(spec.model, row.row_id) if spec and row.row_id else None
        if spec is None or target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "row_not_found", "message": "冲突对应的数据已不存在"},
            )
        try:
            local_fields = json.loads(row.local_row or "{}")
        except json.JSONDecodeError as exc:
            raise _bad_request("invalid_local_row", "本地冲突快照无法读取") from exc
        if not isinstance(local_fields, dict):
            raise _bad_request("invalid_local_row", "本地冲突快照格式无效")
        for field, value in local_fields.items():
            if spec.is_writable(field):
                setattr(target, field, value)
        target.rev = next_rev(session)
        target.updated_at = clamp_updated_at(now_iso())
        session.flush()
        broadcast_rev(target.rev)
    row.resolved_at = now_iso()
    row.resolution = choice
    return {"ok": True, "conflict_id": conflict_id}


@router.get("/devices")
def list_devices(
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """设备列表（不含 token 明文；已吊销的不返回）。"""
    rows = session.execute(select(Device).where(Device.revoked_at.is_(None))).scalars()
    devices = [
        {
            "id": d.id,
            "name": d.name,
            "platform": d.platform,
            "last_seen_at": d.last_seen_at,
            "revoked_at": d.revoked_at,
            "is_current": d.id == device_id,
        }
        for d in rows
    ]
    return {"devices": devices}


@router.put("/devices/{target_id}")
def rename_device(
    target_id: str,
    payload: dict[str, Any],
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """重命名设备（便于分辨手机/电脑/备用机等）。"""
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_name", "message": "设备名不能为空"},
        )
    row = session.get(Device, target_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "设备不存在"},
        )
    row.name = name[:60]
    return {"ok": True, "id": target_id, "name": row.name}


@router.delete("/devices/{target_id}")
def revoke_device(
    target_id: str,
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """吊销设备：令牌立即失效。"""
    row = session.get(Device, target_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "设备不存在"},
        )
    row.revoked_at = now_iso()
    return {"ok": True}


def _conflict_json(row: Conflict) -> dict[str, Any]:
    def parse_snapshot(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    return {
        "id": row.id,
        "entity": row.entity,
        "row_id": row.row_id,
        "device_id": row.device_id,
        "base_rev": row.base_rev,
        "winner": row.winner,
        "server_row": parse_snapshot(row.server_row),
        "local_row": parse_snapshot(row.local_row),
        "created_at": row.created_at,
    }


__all__ = ["router"]
