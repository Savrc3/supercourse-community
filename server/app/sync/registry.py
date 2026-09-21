"""实体注册表：可同步实体的字段白名单 + 模型映射。

技术方案 §5：push 只接受白名单字段，未知字段一律拒绝（``unknown_field``）。
每个实体对应一张 SQLAlchemy 模型；``fields`` 为允许客户端写入的列名集。
"""

from __future__ import annotations

from typing import Any, TypeAlias

from app import models as m

# 服务端强制管控、客户端不可写入的列（通用列与基础设施列）。
_IMMUTABLE_COLUMNS: frozenset[str] = frozenset({"rev", "updated_at", "deleted_at"})


class EntitySpec:
    """单个实体的注册描述。"""

    def __init__(self, model: type[Any], fields: list[str]) -> None:
        self.model: type[Any] = model
        # 白名单 = 模型列（去除 id/rev/updated_at/deleted_at 与客户端禁写列）
        self.fields = frozenset(fields)
        self.table = model.__tablename__

    def is_writable(self, field: str) -> bool:
        return field in self.fields

    def writable_fields(self) -> frozenset[str]:
        return self.fields


# 业务实体：字段清单严格对齐技术方案 §4.2 定稿。
REGISTRY: dict[str, EntitySpec] = {
    "term": EntitySpec(
        m.Term,
        [
            "name",
            "label",
            "start_date",
            "weeks_total",
            "is_current",
            "archived_at",
        ],
    ),
    "lesson_period": EntitySpec(
        m.LessonPeriod,
        ["term_id", "lesson_no", "start_time", "end_time", "big_period"],
    ),
    "course": EntitySpec(
        m.Course,
        [
            "term_id",
            "name",
            "short_name",
            "teacher",
            "code",
            "color",
            "credit",
            "exam_at",
            "exam_room",
            "exam_note",
            "textbook",
            "grade_breakdown",
            "note",
            "sort_order",
        ],
    ),
    "course_slot": EntitySpec(
        m.CourseSlot,
        ["course_id", "weekday", "start_lesson", "end_lesson", "room", "weeks"],
    ),
    "timetable_override": EntitySpec(
        m.TimetableOverride,
        [
            "term_id",
            "day",
            "action",
            "course_id",
            "slot_id",
            "to_weekday",
            "to_start_lesson",
            "to_end_lesson",
            "room",
            "note",
        ],
    ),
    "todo": EntitySpec(
        m.Todo,
        [
            "course_id",
            "kind",
            "title",
            "body",
            "body_text",
            "due_at",
            "start_at",
            "due_all_day",
            "repeat",
            "status",
            "done_at",
            "priority",
            "tags",
            "remind_mode",
            # per-todo 自定义提前量：JSON 数组，元素是负的 ISO 8601 时长（如 ["-PT30M","-P1D"]）。
            # remind_mode=custom 且能解析出至少一个负数时长时生效；否则退回全局 defaults。
            # 字段必须留在同步白名单里：旧客户端仍在推它，删掉会变成 unknown_field 把 op 卡死。
            "remind_offsets",
            "sort_order",
            "created_at",
        ],
    ),
    "media": EntitySpec(
        m.Media,
        [
            "sha256",
            "mime",
            "ext",
            "bytes",
            "width",
            "height",
            "filename",
            "uploaded",
            "created_at",
        ],
    ),
    "attachment": EntitySpec(
        m.Attachment,
        ["media_id", "owner_type", "owner_id", "position", "caption"],
    ),
    "setting": EntitySpec(m.Setting, ["key", "value"]),
}


EntityName: TypeAlias = str


def get_spec(entity: str) -> EntitySpec | None:
    """按实体名取注册表项，未知实体返回 None。"""
    return REGISTRY.get(entity)


__all__ = ["REGISTRY", "EntitySpec", "EntityName", "get_spec"]
