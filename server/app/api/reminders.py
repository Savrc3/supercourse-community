"""提醒设置、试算、日志和通道自测。"""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import CurrentDeviceId
from app.core.config import get_settings
from app.core.db import get_session
from app.models import Course, CourseSlot, ReminderLog, Term, Todo
from app.modules.remind.channels.qq import send_private_message
from app.modules.remind.engine import (
    calculate_events,
    load_config,
    scheduler_ok,
)

router = APIRouter(tags=["reminders"])
Db = Annotated[Session, Depends(get_session)]


@router.get("/reminders/settings")
def reminder_settings(device_id: CurrentDeviceId, session: Db) -> dict[str, Any]:
    return {
        "config": load_config(session),
        "qq_enabled": get_settings().qq_enabled,
        "scheduler_ok": scheduler_ok(),
    }


@router.post("/reminders/preview")
def reminder_preview(
    payload: dict[str, Any], device_id: CurrentDeviceId, session: Db
) -> dict[str, Any]:
    todo_id = str(payload.get("todo_id", ""))
    todo = session.get(Todo, todo_id) if todo_id else None
    if todo is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "待办不存在"})
    events = calculate_events(todo, load_config(session))
    return {
        "events": [
            {"offset": event.offset, "fire_at": event.fire_at.isoformat()} for event in events
        ]
    }


@router.get("/reminders/logs")
def reminder_logs(device_id: CurrentDeviceId, session: Db, limit: int = 100) -> dict[str, Any]:
    rows = session.execute(
        select(ReminderLog).order_by(ReminderLog.created_at.desc()).limit(max(1, min(limit, 500)))
    ).scalars()
    return {
        "logs": [
            {
                "id": row.id,
                "todo_id": row.todo_id,
                "fire_at": row.fire_at,
                "channel": row.channel,
                "status": row.status,
                "detail": json.loads(row.detail or "{}") if row.detail else {},
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@router.post("/reminders/test-qq")
def test_qq(device_id: CurrentDeviceId) -> dict[str, Any]:
    try:
        send_private_message(get_settings(), "超课表提醒通道测试：QQ 通知已连通。")
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail={"code": "qq_failed", "message": str(exc)}
        ) from exc
    return {"ok": True}


@router.get("/diagnostics")
def diagnostics(device_id: CurrentDeviceId, session: Db) -> dict[str, Any]:
    terms = session.execute(select(Term)).scalars().all()
    courses = session.execute(select(Course)).scalars().all()
    slots = session.execute(select(CourseSlot)).scalars().all()
    todos = session.execute(select(Todo)).scalars().all()
    latest_rev = max(
        (cast(int, getattr(row, "rev", 0)) for row in (*terms, *courses, *slots, *todos)),
        default=0,
    )
    return {
        "scheduler_ok": scheduler_ok(),
        "latest_rev": latest_rev,
        "rows": {
            "term": len(terms),
            "course": len(courses),
            "course_slot": len(slots),
            "todo": len(todos),
            "reminder_log": len(session.execute(select(ReminderLog)).scalars().all()),
        },
    }


__all__ = ["router"]
