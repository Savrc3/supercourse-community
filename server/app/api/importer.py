"""教务导入 API：干跑解析 / 确认落库 / 快照回滚。"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.auth import CurrentDeviceId
from app.core.db import get_session
from app.core.journal import now_iso
from app.importers.diff import compute_diff
from app.importers.xls import parse_schedule_file
from app.models import Course, CourseSlot, Meta, Term
from app.sync.push import push_ops

router = APIRouter(tags=["import"])
Db = Annotated[Session, Depends(get_session)]

DRAFT_TTL = 600  # 10 分钟
MAX_IMPORT_BYTES = 20 * 1024 * 1024
_drafts: dict[str, dict[str, Any]] = {}


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "message": message},
    )


@router.post("/import/xls")
async def import_xls(
    file: UploadFile,
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """干跑解析：不写库，返回 draft + 差异预览。"""
    content = await file.read()
    if len(content) > MAX_IMPORT_BYTES:
        raise _bad("file_too_large", "文件过大（>20MB）")
    if not content:
        raise _bad("empty_file", "文件为空")

    result = parse_schedule_file(content, file.filename)
    if result.errors and not result.slots:
        code = (
            "unsupported_format"
            if result.errors[0].startswith("unsupported_format:")
            else "parse_failed"
        )
        raise _bad(code, "解析失败：" + "；".join(result.errors))

    # 找当前学期（或第一个）做差异基准
    term = session.execute(select(Term).where(Term.is_current == 1)).scalar_one_or_none()
    existing_slots: list[CourseSlot] = []
    if term is not None:
        course_list = (
            session.execute(
                select(Course).where(Course.term_id == term.id, Course.deleted_at.is_(None))
            )
            .scalars()
            .all()
        )
        course_ids = [course.id for course in course_list]
        course_name_by_id = {c.id: c.name for c in course_list}
        if course_ids:
            existing_slots = list(
                session.execute(
                    select(CourseSlot).where(
                        CourseSlot.course_id.in_(course_ids),
                        CourseSlot.deleted_at.is_(None),
                    )
                )
                .scalars()
                .all()
            )
    else:
        course_name_by_id = {}

    diff = compute_diff(result.slots, existing_slots, course_name_by_id)
    draft_id = uuid.uuid4().hex
    created_at = time.time()
    expires_at = datetime.fromtimestamp(
        created_at + DRAFT_TTL,
        tz=timezone.utc,
    ).isoformat(timespec="seconds")
    _drafts[draft_id] = {
        "payload": {
            "semester": result.semester,
            "start_date": result.start_date,
            "courses": result.courses,
            "slots": result.slots,
            "warnings": result.warnings,
            "errors": result.errors,
            "term_id": term.id if term else None,
            "diff": diff,
        },
        "created_at": created_at,
        "expires_at": expires_at,
    }
    return {
        "draft_id": draft_id,
        "filename": file.filename or "课表文件",
        "expires_at": expires_at,
        "semester": result.semester,
        "start_date": result.start_date,
        "courses": result.courses,
        "slots": result.slots,
        "warnings": result.warnings,
        "errors": result.errors,
        "diff": diff,
    }


@router.post("/import/commit")
def import_commit(
    payload: dict[str, Any],
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """确认落库：先快照当前学期，再事务内走唯一写路径。"""
    draft_id = str(payload.get("draft_id", ""))
    draft = _get_draft(draft_id)
    if draft is None:
        raise _bad("draft_expired", "draft 已过期，请重新上传")

    d = draft["payload"]
    term = session.get(Term, d["term_id"]) if d.get("term_id") else None
    if term is None:
        term = _ensure_term(session, d)

    accepted = payload.get("accepted")
    if accepted is None:
        accepted = payload.get("slots_to_apply")
    if accepted is None:
        accepted = [
            {"kind": item["kind"], "index": item.get("index"), "row_id": item.get("row_id")}
            for kind in ("added", "changed")
            for item in d.get("diff", {}).get(kind, [])
        ]
    if not isinstance(accepted, list):
        raise _bad("invalid_selection", "accepted 必须是数组")

    selected_items = _select_diff_items(d, accepted)

    # 快照当前学期（存 meta）
    snapshot = _snapshot_term(session, term)
    session.merge(Meta(key=f"snapshot:{term.id}", value=json.dumps(snapshot)))

    # 构造 push ops 落库（course + course_slot）
    ops = _build_ops(session, term, d, selected_items)
    results = push_ops(session, ops, device_id)
    applied = sum(1 for r in results if r.status in ("applied", "merged"))
    rejected = [r for r in results if r.status == "rejected"]
    if rejected:
        raise _bad("import_rejected", "部分导入项未通过校验")

    return {
        "ok": True,
        "draft_id": draft_id,
        "term_id": term.id,
        "applied": applied,
        "total_ops": len(ops),
        "snapshot_done": True,
    }


@router.post("/import/rollback")
def import_rollback(
    payload: dict[str, Any],
    device_id: CurrentDeviceId,
    session: Db,
) -> dict[str, Any]:
    """一键回滚：从快照恢复当前学期（回滚后删快照）。"""
    term_id = str(payload.get("term_id", ""))
    row = session.get(Meta, f"snapshot:{term_id}")
    if row is None:
        raise _bad("no_snapshot", "没有可回滚的快照")
    snapshot = json.loads(row.value)
    term = session.get(Term, term_id)
    if term is None:
        raise _bad("no_term", "学期不存在")
    _restore_term(session, term, snapshot)
    session.delete(row)
    return {"ok": True}


def _get_draft(draft_id: str) -> dict[str, Any] | None:
    entry = _drafts.get(draft_id)
    if entry is None:
        return None
    if time.time() - entry["created_at"] > DRAFT_TTL:
        _drafts.pop(draft_id, None)
        return None
    return entry


def _diff_item_key(item: dict[str, Any]) -> str:
    kind = str(item.get("kind", ""))
    if kind in ("added", "changed"):
        return f"{kind}:{item.get('index')}"
    return f"removed:{item.get('row_id')}"


def _selection_key(raw: Any) -> str | None:
    if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit()):
        return f"index:{int(raw)}"
    if isinstance(raw, dict):
        kind = str(raw.get("kind", ""))
        if kind in ("added", "changed") and str(raw.get("index", "")).isdigit():
            return f"{kind}:{int(raw['index'])}"
        if kind == "removed" and raw.get("row_id"):
            return f"removed:{raw['row_id']}"
        return None
    if isinstance(raw, str) and raw.startswith(("added:", "changed:", "removed:")):
        return raw
    return None


def _select_diff_items(draft: dict[str, Any], accepted: list[Any]) -> list[dict[str, Any]]:
    """从 draft 中解析并校验客户端勾选，兼容旧版的 slot index 数组。"""
    by_key: dict[str, dict[str, Any]] = {}
    by_index: dict[str, dict[str, Any]] = {}
    for kind in ("added", "changed", "removed"):
        for item in draft.get("diff", {}).get(kind, []):
            by_key[_diff_item_key(item)] = item
            if kind in ("added", "changed"):
                by_index[f"index:{item.get('index')}"] = item

    selected: list[dict[str, Any]] = []
    for raw in accepted:
        key = _selection_key(raw)
        item = by_index.get(key) if key and key.startswith("index:") else by_key.get(key or "")
        if item is None:
            raise _bad("invalid_selection", "导入选择已失效，请重新上传")
        selected.append(item)
    return selected


def _ensure_term(session: Session, d: dict[str, Any]) -> Term:
    name = d.get("semester") or "导入学期"
    existing = session.execute(select(Term).where(Term.name == name)).scalar_one_or_none()
    if existing:
        return existing
    from app.core.journal import next_rev as nr

    term = Term(
        id=str(uuid.uuid4()),
        rev=nr(session),
        updated_at=now_iso(),
        name=name,
        label=None,
        start_date=d.get("start_date") or now_iso()[:10],
        weeks_total=20,
        is_current=1,
    )
    session.add(term)
    session.flush()
    return term


def _snapshot_term(session: Session, term: Term) -> dict[str, Any]:
    course_ids = list(session.execute(select(Course.id).where(Course.term_id == term.id)).scalars())
    courses = session.execute(select(Course).where(Course.term_id == term.id)).scalars().all()
    slots = (
        session.execute(select(CourseSlot).where(CourseSlot.course_id.in_(course_ids)))
        .scalars()
        .all()
        if course_ids
        else []
    )
    return {
        "term": {
            "id": term.id,
            "rev": term.rev,
            "updated_at": term.updated_at,
            "deleted_at": term.deleted_at,
            "name": term.name,
            "label": term.label,
            "start_date": term.start_date,
            "weeks_total": term.weeks_total,
            "is_current": term.is_current,
            "archived_at": term.archived_at,
        },
        "courses": [
            {
                "id": c.id,
                "rev": c.rev,
                "updated_at": c.updated_at,
                "deleted_at": c.deleted_at,
                "term_id": c.term_id,
                "name": c.name,
                "short_name": c.short_name,
                "teacher": c.teacher,
                "code": c.code,
                "color": c.color,
                "credit": c.credit,
                "exam_at": c.exam_at,
                "exam_room": c.exam_room,
                "exam_note": c.exam_note,
                "textbook": c.textbook,
                "grade_breakdown": c.grade_breakdown,
                "note": c.note,
                "sort_order": c.sort_order,
            }
            for c in courses
        ],
        "slots": [
            {
                "id": s.id,
                "rev": s.rev,
                "updated_at": s.updated_at,
                "deleted_at": s.deleted_at,
                "course_id": s.course_id,
                "weekday": s.weekday,
                "start_lesson": s.start_lesson,
                "end_lesson": s.end_lesson,
                "room": s.room,
                "weeks": s.weeks,
            }
            for s in slots
        ],
    }


def _restore_term(session: Session, term: Term, snap: dict[str, Any]) -> None:
    # 删除现有 course/slot
    cids = list(session.execute(select(Course.id).where(Course.term_id == term.id)).scalars())
    if cids:
        session.execute(delete(CourseSlot).where(CourseSlot.course_id.in_(cids)))
        session.execute(delete(Course).where(Course.id.in_(cids)))
    term_data = snap.get("term", {})
    for field in (
        "rev",
        "updated_at",
        "deleted_at",
        "name",
        "label",
        "start_date",
        "weeks_total",
        "is_current",
        "archived_at",
    ):
        if field in term_data:
            setattr(term, field, term_data[field])

    # 重新插入快照
    for c in snap.get("courses", []):
        session.add(Course(**c))
    for s in snap.get("slots", []):
        session.add(CourseSlot(**s))


def _build_ops(
    session: Session,
    term: Term,
    d: dict[str, Any],
    selected_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把确认项转成 push ops，新增/变更/删除都走统一同步写路径。"""
    ops: list[dict[str, Any]] = []
    course_by_key: dict[tuple[str, str], str] = {}
    existing_courses = session.execute(
        select(Course).where(Course.term_id == term.id, Course.deleted_at.is_(None))
    ).scalars()
    for course in existing_courses:
        key = (course.name.strip(), (course.code or "").strip().lower())
        course_by_key[key] = course.id

    course_info_by_key = {
        (
            str(course.get("name") or "").strip(),
            str(course.get("code") or "").strip().lower(),
        ): course
        for course in d.get("courses", [])
    }

    for item in selected_items:
        kind = str(item.get("kind", ""))
        if kind == "removed":
            row = session.get(CourseSlot, str(item.get("row_id", "")))
            if row is None or row.deleted_at is not None:
                continue
            ops.append(
                {
                    "op_id": f"imp-del-{uuid.uuid4().hex}",
                    "entity": "course_slot",
                    "id": row.id,
                    "set": {},
                    "base_rev": row.rev,
                    "deleted": True,
                }
            )
            continue

        slot = item.get("after") or {}
        name = str(slot.get("course_name") or "").strip()
        code = str(slot.get("code") or "").strip().lower()
        course_id: str | None = None
        if kind == "changed":
            row = session.get(CourseSlot, str(item.get("row_id", "")))
            if row is None or row.deleted_at is not None:
                continue
            course_id = row.course_id
            ops.append(
                {
                    "op_id": f"imp-chg-{uuid.uuid4().hex}",
                    "entity": "course_slot",
                    "id": row.id,
                    "set": {
                        "course_id": row.course_id,
                        "weekday": slot.get("weekday"),
                        "start_lesson": slot.get("start_lesson"),
                        "end_lesson": slot.get("end_lesson"),
                        "room": slot.get("room"),
                        "weeks": slot.get("weeks"),
                    },
                    "base_rev": row.rev,
                }
            )
            continue

        key = (name, code)
        course_id = course_by_key.get(key)
        if course_id is None:
            course_id = str(uuid.uuid4())
            course_by_key[key] = course_id
            course_info = course_info_by_key.get(key, {})
            ops.append(
                {
                    "op_id": f"imp-c-{uuid.uuid4().hex}",
                    "entity": "course",
                    "id": course_id,
                    "set": {
                        "term_id": term.id,
                        "name": name,
                        "teacher": course_info.get("teacher"),
                        "code": course_info.get("code"),
                        "color": course_info.get("color") or 0,
                    },
                    "base_rev": 0,
                }
            )
        ops.append(
            {
                "op_id": f"imp-s-{uuid.uuid4().hex}",
                "entity": "course_slot",
                "id": str(uuid.uuid4()),
                "set": {
                    "course_id": course_id,
                    "weekday": slot.get("weekday"),
                    "start_lesson": slot.get("start_lesson"),
                    "end_lesson": slot.get("end_lesson"),
                    "room": slot.get("room"),
                    "weeks": slot.get("weeks"),
                },
                "base_rev": 0,
            }
        )
    return ops


__all__ = ["router"]
