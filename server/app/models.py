"""全部 ORM 模型（严格对齐技术方案 §4 定稿 DDL，不自行改动字段）。"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Seq(Base):
    """全局单调 rev 取号器（单行：k=1）。"""

    __tablename__ = "seq"

    k: Mapped[int] = mapped_column(Integer, primary_key=True)
    v: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("k", name="uq_seq_k"),)


class Meta(Base):
    """键值元数据（schema_version、tombstone_floor 等）。"""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)


class Term(Base):
    __tablename__ = "term"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String)
    start_date: Mapped[str] = mapped_column(String, nullable=False)
    weeks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    is_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("idx_term_rev", "rev"),)


class LessonPeriod(Base):
    __tablename__ = "lesson_period"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    term_id: Mapped[str] = mapped_column(String, ForeignKey("term.id"), nullable=False)
    lesson_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[str] = mapped_column(String, nullable=False)
    big_period: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("idx_lesson_period_rev", "rev"),)


class Course(Base):
    __tablename__ = "course"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    term_id: Mapped[str] = mapped_column(String, ForeignKey("term.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    short_name: Mapped[str | None] = mapped_column(String)
    teacher: Mapped[str | None] = mapped_column(String)
    code: Mapped[str | None] = mapped_column(String)
    color: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit: Mapped[float | None] = mapped_column(Float)
    exam_at: Mapped[str | None] = mapped_column(String)
    exam_room: Mapped[str | None] = mapped_column(String)
    exam_note: Mapped[str | None] = mapped_column(String)
    textbook: Mapped[str | None] = mapped_column(String)
    grade_breakdown: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("idx_course_rev", "rev"),)


class CourseSlot(Base):
    __tablename__ = "course_slot"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("course.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_lesson: Mapped[int] = mapped_column(Integer, nullable=False)
    end_lesson: Mapped[int] = mapped_column(Integer, nullable=False)
    room: Mapped[str | None] = mapped_column(String)
    weeks: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("idx_course_slot_rev", "rev"),)


class TimetableOverride(Base):
    __tablename__ = "timetable_override"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    term_id: Mapped[str] = mapped_column(String, ForeignKey("term.id"), nullable=False)
    day: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    course_id: Mapped[str | None] = mapped_column(String)
    slot_id: Mapped[str | None] = mapped_column(String)
    to_weekday: Mapped[int | None] = mapped_column(Integer)
    to_start_lesson: Mapped[int | None] = mapped_column(Integer)
    to_end_lesson: Mapped[int | None] = mapped_column(Integer)
    room: Mapped[str | None] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("idx_timetable_override_rev", "rev"),)


class Todo(Base):
    __tablename__ = "todo"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    course_id: Mapped[str | None] = mapped_column(String, ForeignKey("course.id"))
    kind: Mapped[str] = mapped_column(String, nullable=False, default="todo")
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False, default="{}")
    body_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    due_at: Mapped[str | None] = mapped_column(String)
    start_at: Mapped[str | None] = mapped_column(String)
    due_all_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    repeat: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="0")
    done_at: Mapped[str | None] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tags: Mapped[str] = mapped_column(String, nullable=False, default="[]")
    remind_mode: Mapped[str] = mapped_column(String, nullable=False, default="inherit")
    remind_offsets: Mapped[str | None] = mapped_column(String)
    sort_order: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("idx_todo_rev", "rev"),)


class Media(Base):
    __tablename__ = "media"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    mime: Mapped[str] = mapped_column(String, nullable=False)
    ext: Mapped[str] = mapped_column(String, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    filename: Mapped[str | None] = mapped_column(String)
    uploaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("idx_media_rev", "rev"),
        UniqueConstraint("sha256", name="uq_media_sha"),
    )


class Attachment(Base):
    __tablename__ = "attachment"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    media_id: Mapped[str] = mapped_column(String, ForeignKey("media.id"), nullable=False)
    owner_type: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caption: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("idx_attachment_rev", "rev"),)


class Setting(Base):
    __tablename__ = "setting"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rev: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(String)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("idx_setting_rev", "rev"),
        UniqueConstraint("key", name="uq_setting_key"),
    )


class Device(Base):
    __tablename__ = "device"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    platform: Mapped[str | None] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str | None] = mapped_column(String)
    last_seen_at: Mapped[str | None] = mapped_column(String)
    revoked_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (UniqueConstraint("token_hash", name="uq_device_token"),)


class Account(Base):
    """单用户模式的登录账号；设备令牌仍只作为内部会话凭证。"""

    __tablename__ = "account"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("username", name="uq_account_username"),)


class Pairing(Base):
    __tablename__ = "pairing"

    code_hash: Mapped[str] = mapped_column(String, primary_key=True)
    created_by: Mapped[str | None] = mapped_column(String)
    expires_at: Mapped[str | None] = mapped_column(String)
    used_at: Mapped[str | None] = mapped_column(String)


class OpLog(Base):
    __tablename__ = "op_log"

    client_op_id: Mapped[str] = mapped_column(String, primary_key=True)
    device_id: Mapped[str | None] = mapped_column(String)
    entity: Mapped[str | None] = mapped_column(String)
    row_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    applied_rev: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str | None] = mapped_column(String)


class Conflict(Base):
    __tablename__ = "conflict"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    entity: Mapped[str | None] = mapped_column(String)
    row_id: Mapped[str | None] = mapped_column(String)
    device_id: Mapped[str | None] = mapped_column(String)
    base_rev: Mapped[int | None] = mapped_column(Integer)
    server_row: Mapped[str | None] = mapped_column(String)
    local_row: Mapped[str | None] = mapped_column(String)
    winner: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str | None] = mapped_column(String)
    resolved_at: Mapped[str | None] = mapped_column(String)
    resolution: Mapped[str | None] = mapped_column(String)


class ReminderLog(Base):
    __tablename__ = "reminder_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    todo_id: Mapped[str | None] = mapped_column(String)
    fire_at: Mapped[str | None] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str | None] = mapped_column(String)

    __table_args__ = (UniqueConstraint("fingerprint", name="uq_reminder_fp"),)


# 供 Alembic autogenerate 与模块导入引用
__all__ = [
    "Seq",
    "Meta",
    "Term",
    "LessonPeriod",
    "Course",
    "CourseSlot",
    "TimetableOverride",
    "Todo",
    "Media",
    "Attachment",
    "Setting",
    "Device",
    "Account",
    "Pairing",
    "OpLog",
    "Conflict",
    "ReminderLog",
]
