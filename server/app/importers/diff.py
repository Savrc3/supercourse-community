"""教务导入差异比对：新增 / 变更 / 删除三类（FR-206）。

差异结果是确认页使用的稳定契约：

* ``added`` / ``changed`` 带解析结果的 ``index``，便于用户逐条选择；
* ``changed`` / ``removed`` 带现有库的 ``row_id`` 和 ``before`` 快照；
* 新增、变更默认 ``selected=True``，删除默认 ``selected=False``；
* 课程名 + 星期 + 起始小节 + 周次用于对齐，教室和结束小节变化归为变更。
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _canonical_weeks(value: Any) -> str:
    """让等价但格式不同的周次 JSON 不产生假差异。"""
    if not isinstance(value, str):
        return str(value or "")
    raw = value.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _slot_fingerprint(slot: dict[str, Any]) -> tuple[str, int, int, str]:
    return (
        str(slot.get("course_name", "") or "").strip(),
        _as_int(slot.get("weekday")),
        _as_int(slot.get("start_lesson")),
        _canonical_weeks(slot.get("weeks")),
    )


def _row_to_fingerprint(
    row: Any,
    course_name_by_id: dict[str, str],
) -> tuple[str, int, int, str]:
    # CourseSlot 只有 course_id，需通过映射取课程名。
    course_id = str(getattr(row, "course_id", "") or "")
    name = course_name_by_id.get(course_id, getattr(row, "name", "")) or ""
    return (
        str(name).strip(),
        _as_int(getattr(row, "weekday", 0)),
        _as_int(getattr(row, "start_lesson", 0)),
        _canonical_weeks(getattr(row, "weeks", "")),
    )


def _slot_snapshot(slot: dict[str, Any]) -> dict[str, Any]:
    return {
        "course_name": slot.get("course_name", ""),
        "code": slot.get("code"),
        "weekday": _as_int(slot.get("weekday")),
        "start_lesson": _as_int(slot.get("start_lesson")),
        "end_lesson": _as_int(slot.get("end_lesson")),
        "room": slot.get("room") or None,
        "weeks": slot.get("weeks", ""),
    }


def _row_snapshot(row: Any, course_name_by_id: dict[str, str]) -> dict[str, Any]:
    course_id = str(getattr(row, "course_id", "") or "")
    return {
        "row_id": getattr(row, "id", ""),
        "course_id": course_id,
        "course_name": course_name_by_id.get(course_id, getattr(row, "name", "")),
        "weekday": _as_int(getattr(row, "weekday", 0)),
        "start_lesson": _as_int(getattr(row, "start_lesson", 0)),
        "end_lesson": _as_int(getattr(row, "end_lesson", 0)),
        "room": getattr(row, "room", None) or None,
        "weeks": getattr(row, "weeks", ""),
    }


def compute_diff(
    parsed_slots: list[dict[str, Any]],
    existing_rows: list[Any],
    course_name_by_id: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """输出确认页可直接消费的 ``{added, changed, removed}``。

    对齐键不包含结束小节和教室，因此它们发生变化时会进入 ``changed``，而
    星期、起始小节或周次变化会表现为一条删除 + 一条新增，避免静默覆盖。
    重复键按出现顺序一一配对，不会因为字典覆盖而漏报删除项。
    """
    name_map = course_name_by_id or {}
    existing_by_key: dict[tuple[str, int, int, str], list[Any]] = defaultdict(list)
    for row in existing_rows:
        key = _row_to_fingerprint(row, name_map)
        if key[0]:
            existing_by_key[key].append(row)

    added: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    for index, slot in enumerate(parsed_slots):
        key = _slot_fingerprint(slot)
        if not key[0]:
            continue
        matches = existing_by_key.get(key)
        row = matches.pop(0) if matches else None
        if row is None:
            added.append(
                {
                    "kind": "added",
                    "index": index,
                    "selected": True,
                    "before": None,
                    "after": _slot_snapshot(slot),
                }
            )
        elif _row_changed(row, slot):
            changed.append(
                {
                    "kind": "changed",
                    "index": index,
                    "row_id": getattr(row, "id", ""),
                    "selected": True,
                    "before": _row_snapshot(row, name_map),
                    "after": _slot_snapshot(slot),
                }
            )

    removed: list[dict[str, Any]] = []
    for rows in existing_by_key.values():
        removed.extend(
            {
                "kind": "removed",
                "row_id": getattr(row, "id", ""),
                "selected": False,
                "before": _row_snapshot(row, name_map),
                "after": None,
            }
            for row in rows
        )

    return {"added": added, "changed": changed, "removed": removed}


def _row_changed(row: Any, slot: dict[str, Any]) -> bool:
    return (_as_int(getattr(row, "end_lesson", 0)) != _as_int(slot.get("end_lesson"))) or (
        (getattr(row, "room", None) or None) != (slot.get("room") or None)
    )


__all__ = ["compute_diff"]
