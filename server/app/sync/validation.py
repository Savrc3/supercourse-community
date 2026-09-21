"""op / 恢复行的字段校验：白名单之外还有引用、必填、取值域与媒体路径安全。

技术方案 §5 要求「字段白名单 + 校验，非法 op 回明确错误码」。校验分两层：

* **通用层**（必填、外键引用、媒体路径）：push 与 restore 都要过。这一层
  挡的是「会让 SQLite 抛 IntegrityError → 端点 500 → 客户端整批 op 卡在
  outbox 反复重试」的输入。
* **取值域层**（枚举、数值区间、JSON 形状）：只在 push 生效。历史数据可能
  是合法但更宽松的形状，恢复时应尽量原样落库而不是被拒。

错误码是稳定字符串；缺字段时形如 ``missing_field:title``，引用缺失时形如
``invalid_reference:course_id``，便于前端直接展示。
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeGuard

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.media_rules import ALLOWED_EXTENSIONS, ALLOWED_MIMES, ID_RE

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 服务端负责填充或不可写的通用列：缺失不算「必填缺失」。
_SERVER_FILLED: frozenset[str] = frozenset({"id", "rev", "updated_at", "deleted_at", "created_at"})

MAX_LESSON_NO = 24
# 学期周数/周次的上限：只为挡住明显垃圾值（9999），不放宽到会误伤正常输入。
MAX_WEEKS_TOTAL = 100
VALID_PARITY: frozenset[str] = frozenset({"all", "odd", "even"})

# 恢复时按依赖顺序落库，父行先于子行（手写备份可能顺序任意）。
RESTORE_ORDER: tuple[str, ...] = (
    "term",
    "lesson_period",
    "course",
    "course_slot",
    "timetable_override",
    "todo",
    "media",
    "attachment",
    "setting",
)


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def check_required(model: Any, fields: dict[str, Any]) -> str | None:
    """新建行是否缺必填列（NOT NULL 且无默认值）。

    SQLite 由 ``foreign_keys=ON`` 与 NOT NULL 约束把关，但违反时抛的是
    IntegrityError；在写入前拦下来才能返回明确错误码而不是 500。
    """
    for column in model.__table__.columns:
        if column.nullable or column.default is not None or column.server_default is not None:
            continue
        if column.name in _SERVER_FILLED:
            continue
        if column.name not in fields:
            return f"missing_field:{column.name}"
    return None


def check_references(session: Session, model: Any, fields: dict[str, Any]) -> str | None:
    """外键列引用的行必须已存在（软删行仍在表里，因此照常通过）。"""
    for column in model.__table__.columns:
        if column.name not in fields:
            continue
        value = fields[column.name]
        if value is None:
            continue
        for key in column.foreign_keys:
            target = key.column
            found = session.execute(select(target).where(target == value).limit(1)).first()
            if found is None:
                return f"invalid_reference:{column.name}"
    return None


def check_media_fields(row_id: str, fields: dict[str, Any], *, strict: bool) -> str | None:
    """媒体 id/ext/mime/sha256 校验（安全相关，push 与 restore 都必须过）。"""
    if not ID_RE.fullmatch(row_id or ""):
        return "invalid_media_id"
    ext = fields.get("ext")
    if ext is not None and ext not in ALLOWED_EXTENSIONS:
        return "invalid_media_ext"
    if not strict:
        return None
    mime = fields.get("mime")
    if mime is not None and mime not in ALLOWED_MIMES:
        return "invalid_media_mime"
    sha256 = fields.get("sha256")
    if sha256 is not None and not (isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256)):
        return "invalid_sha256"
    size = fields.get("bytes")
    if size is not None and (not _is_int(size) or size < 0):
        return "invalid_field:bytes"
    uploaded = fields.get("uploaded")
    if uploaded is not None and uploaded not in (0, 1):
        return "invalid_field:uploaded"
    return None


def _check_weeks(value: Any) -> str | None:
    """``weeks`` 必须是可解析的 JSON；形状按前端 WeeksSpec 校验（多键允许）。"""
    if not isinstance(value, str) or not value.strip():
        return "invalid_weeks"
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return "invalid_weeks"
    if not isinstance(parsed, dict):
        return "invalid_weeks"
    parity = parsed.get("parity")
    if parity is not None and parity not in VALID_PARITY:
        return "invalid_weeks"
    for key in ("ranges",):
        if key in parsed:
            ranges = parsed[key]
            if not isinstance(ranges, list):
                return "invalid_weeks"
            for item in ranges:
                if not isinstance(item, list) or len(item) != 2:
                    return "invalid_weeks"
                low, high = item
                if not _is_int(low) or not _is_int(high):
                    return "invalid_weeks"
                if low < 1 or high < low or high > MAX_WEEKS_TOTAL:
                    return "invalid_weeks"
    for key in ("only", "except"):
        if key in parsed:
            values = parsed[key]
            if not isinstance(values, list) or not all(
                _is_int(v) and 1 <= v <= MAX_WEEKS_TOTAL for v in values
            ):
                return "invalid_weeks"
    return None


def check_ranges(entity: str, fields: dict[str, Any]) -> str | None:
    """取值域校验（仅 push）。越界值会让前端渲染出错或整块课表算不出来。"""
    if entity == "todo":
        if "status" in fields and str(fields["status"]) not in {"0", "1"}:
            return "invalid_status"
        priority = fields.get("priority")
        if priority is not None and (not _is_int(priority) or priority not in (0, 1, 2)):
            return "invalid_priority"
        all_day = fields.get("due_all_day")
        if all_day is not None and (not _is_int(all_day) or all_day not in (0, 1)):
            return "invalid_field:due_all_day"
    elif entity == "course_slot":
        weekday = fields.get("weekday")
        if weekday is not None and (not _is_int(weekday) or not 1 <= weekday <= 7):
            return "invalid_weekday"
        for name in ("start_lesson", "end_lesson"):
            lesson = fields.get(name)
            if lesson is not None and (not _is_int(lesson) or not 1 <= lesson <= MAX_LESSON_NO):
                return f"invalid_lesson:{name}"
        start = fields.get("start_lesson")
        end = fields.get("end_lesson")
        if _is_int(start) and _is_int(end) and end < start:
            return "invalid_lesson_range"
        if "weeks" in fields:
            error = _check_weeks(fields["weeks"])
            if error:
                return error
    elif entity == "term":
        weeks_total = fields.get("weeks_total")
        if weeks_total is not None and (
            not _is_int(weeks_total) or not 1 <= weeks_total <= MAX_WEEKS_TOTAL
        ):
            return "invalid_weeks_total"
        start_date = fields.get("start_date")
        if start_date is not None:
            if not isinstance(start_date, str) or not _DATE_RE.fullmatch(start_date):
                return "invalid_date"
            try:
                year, month, day = (int(part) for part in start_date.split("-"))
                from datetime import date as _date

                _date(year, month, day)
            except ValueError:
                return "invalid_date"
        is_current = fields.get("is_current")
        if is_current is not None and (not _is_int(is_current) or is_current not in (0, 1)):
            return "invalid_field:is_current"
    elif entity == "setting":
        key = fields.get("key")
        if key is not None and (not isinstance(key, str) or not key.strip() or len(key) > 128):
            return "invalid_field:key"
    elif entity == "attachment":
        position = fields.get("position")
        if position is not None and (not _is_int(position) or position < 0):
            return "invalid_field:position"
    return None


def validate_op_fields(
    session: Session,
    entity: str,
    model: Any,
    row_id: str,
    fields: dict[str, Any],
    *,
    is_new: bool,
) -> str | None:
    """push 路径的完整校验（通用层 + 取值域层）。返回错误码或 None。"""
    if entity == "media":
        error = check_media_fields(row_id, fields, strict=True)
        if error:
            return error
    # 先查取值域再查必填：既有数据里「状态是旧枚举值」这类 op 应该继续拿到
    # invalid_status，而不是被必填检查抢先报成 missing_field。
    error = check_ranges(entity, fields)
    if error:
        return error
    if is_new:
        error = check_required(model, fields)
        if error:
            return error
    return check_references(session, model, fields)


def validate_restore_row(
    session: Session,
    entity: str,
    model: Any,
    row_id: str,
    fields: dict[str, Any],
) -> str | None:
    """restore 路径的校验：只拦「会 500 或越界读文件」的行。"""
    if entity == "media":
        error = check_media_fields(row_id, fields, strict=False)
        if error:
            return error
    error = check_required(model, fields)
    if error:
        return error
    error = check_references(session, model, fields)
    if error:
        return error
    return None


__all__ = [
    "RESTORE_ORDER",
    "check_media_fields",
    "check_ranges",
    "check_references",
    "check_required",
    "validate_op_fields",
    "validate_restore_row",
]
