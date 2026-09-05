"""提醒时间计算、幂等发送与 APScheduler 接线。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_engine, session_scope
from app.core.journal import now_iso
from app.models import Course, CourseSlot, LessonPeriod, ReminderLog, Setting, Term, Todo
from app.modules.remind.channels.qq import send_private_message

SHANGHAI = ZoneInfo("Asia/Shanghai")
TICK_GRACE = timedelta(seconds=120)
MAX_ATTEMPTS = 3
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5))
CONFIG_KEY = "reminder.config"
REMINDER_KINDS = {"todo", "class"}

DEFAULT_CONFIG: dict[str, Any] = {
    "defaults": {
        "todo": ["-P1D"],
        "class": ["-PT15M"],
    },
    "channels": {
        "todo": ["qq", "mobile", "windows"],
        "class": ["qq", "mobile", "windows"],
    },
}


@dataclass(frozen=True)
class ReminderEvent:
    todo_id: str
    fire_at: datetime
    offset: str


@dataclass(frozen=True)
class ClassReminderEvent:
    event_id: str
    course_id: str
    course_name: str
    room: str | None
    starts_at: datetime
    fire_at: datetime


def parse_iso_duration(raw: str) -> timedelta | None:
    """解析提醒使用的负 ISO 8601 时长，如 -P1D、-PT2H、-PT10M。"""
    match = re.fullmatch(
        r"(?P<sign>-)?P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?",
        raw.strip().upper(),
    )
    if not match or not any(match.group(key) for key in ("days", "hours", "minutes")):
        return None
    value = timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
    )
    return -value if match.group("sign") else value


def due_datetime(due_at: str, due_all_day: int) -> datetime | None:
    """把日期/日期时间统一解释为上海时区；全天以 09:00 为提醒基准。"""
    try:
        if len(due_at) == 10 or due_all_day == 1:
            day = date.fromisoformat(due_at[:10])
            return datetime.combine(day, time(9), SHANGHAI)
        parsed = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return parsed.astimezone(SHANGHAI)
    except ValueError:
        return None


def _defaults_for(todo: Todo, config: dict[str, Any]) -> list[str]:
    if todo.kind != "todo":
        return []
    defaults = config.get("defaults", {})
    values = defaults.get(todo.kind) or defaults.get("todo") or []
    return [str(value) for value in values if parse_iso_duration(str(value)) is not None]


def _offsets_for(todo: Todo, config: dict[str, Any]) -> list[str]:
    if todo.remind_mode == "off":
        return []
    return _defaults_for(todo, config)


def channel_enabled_for(todo: Todo, config: dict[str, Any], channel: str) -> bool:
    """按待办类型判断通道；旧的考试/报名/其他类型不再触发。"""
    if todo.kind not in REMINDER_KINDS:
        return False
    kind = todo.kind
    channels = config.get("channels", {})
    selected = channels.get(kind, []) if isinstance(channels, dict) else []
    return channel in selected if isinstance(selected, list) else False


def calculate_events(
    todo: Todo,
    config: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> list[ReminderEvent]:
    """计算一条待办的提醒时刻；不负责发送，也不自动补发过期提醒。"""
    if todo.deleted_at or todo.status != "0" or not todo.due_at:
        return []
    due = due_datetime(todo.due_at, todo.due_all_day)
    if due is None:
        return []
    active_config = config or DEFAULT_CONFIG
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    events = [
        ReminderEvent(todo.id, due + parsed, raw)
        for raw in _offsets_for(todo, active_config)
        if (parsed := parse_iso_duration(raw)) is not None and due + parsed >= current - TICK_GRACE
    ]
    return sorted(events, key=lambda event: event.fire_at)


def calculate_class_events(
    session: Session,
    config: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> list[ClassReminderEvent]:
    """计算当前学期未来课程的上课前 15 分钟提醒。"""
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    active_config = config or DEFAULT_CONFIG
    offsets = active_config.get("defaults", {}).get("class", ["-PT15M"])
    offset = parse_iso_duration(str(offsets[0])) if offsets else None
    if offset is None:
        return []
    terms = (
        session.execute(
            select(Term).where(Term.deleted_at.is_(None)).order_by(Term.is_current.desc())
        )
        .scalars()
        .all()
    )
    term = terms[0] if terms else None
    if term is None:
        return []
    courses = {
        row.id: row
        for row in session.execute(
            select(Course).where(Course.deleted_at.is_(None), Course.term_id == term.id)
        )
        .scalars()
        .all()
    }
    periods = {
        row.lesson_no: row
        for row in session.execute(
            select(LessonPeriod).where(
                LessonPeriod.deleted_at.is_(None), LessonPeriod.term_id == term.id
            )
        )
        .scalars()
        .all()
    }
    slots = (
        session.execute(select(CourseSlot).where(CourseSlot.deleted_at.is_(None))).scalars().all()
    )
    result: list[ClassReminderEvent] = []
    for day_index in range(56):
        day = current.date() + timedelta(days=day_index)
        week = max(
            1,
            min(
                (day - date.fromisoformat(term.start_date)).days // 7 + 1,
                term.weeks_total,
            ),
        )
        for slot in slots:
            if slot.course_id not in courses or slot.weekday != day.isoweekday():
                continue
            try:
                spec = json.loads(slot.weeks)
                ranges = spec.get("ranges", [])
                only = spec.get("only", [])
                excepted = spec.get("except", [])
                allowed = (
                    (not ranges and not only)
                    or week in only
                    or any(a <= week <= b for a, b in ranges)
                )
                if (
                    week in excepted
                    or (spec.get("parity") == "odd" and week % 2 == 0)
                    or (spec.get("parity") == "even" and week % 2 == 1)
                ):
                    allowed = False
            except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
                allowed = True
            period = periods.get(slot.start_lesson)
            course = courses.get(slot.course_id)
            if not allowed or period is None or course is None:
                continue
            try:
                hour, minute = (int(value) for value in period.start_time.split(":", 1))
            except (TypeError, ValueError):
                continue
            starts_at = datetime.combine(day, time(hour, minute), SHANGHAI)
            fire_at = starts_at + offset
            if fire_at < current - TICK_GRACE:
                continue
            result.append(
                ClassReminderEvent(
                    f"{slot.id}:{day.isoformat()}",
                    course.id,
                    course.name,
                    slot.room,
                    starts_at,
                    fire_at,
                )
            )
    return sorted(result, key=lambda event: event.fire_at)[:64]


def fingerprint(todo_id: str, fire_at: datetime, channel: str) -> str:
    raw = f"{todo_id}|{fire_at.astimezone(SHANGHAI).isoformat()}|{channel}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_config(session: Session) -> dict[str, Any]:
    row = session.execute(
        select(Setting).where(Setting.key == CONFIG_KEY, Setting.deleted_at.is_(None))
    ).scalar_one_or_none()
    if row is None:
        return cast(dict[str, Any], json.loads(json.dumps(DEFAULT_CONFIG)))
    try:
        stored = json.loads(row.value)
    except json.JSONDecodeError:
        stored = {}
    return _merge_config(DEFAULT_CONFIG, stored if isinstance(stored, dict) else {})


def _merge_config(default: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    result = cast(dict[str, Any], json.loads(json.dumps(default)))
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result


def reminder_message(todo: Todo, course_name: str, offset: str) -> str:
    course = course_name or "杂事"
    return f"超课表提醒\n{course}\n{todo.title}\n将在 {offset} 后到期。"


def _detail(row: ReminderLog) -> dict[str, Any]:
    try:
        parsed = json.loads(row.detail or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}


def _send_message(
    session: Session,
    settings: Settings,
    *,
    event_id: str,
    todo_id: str | None,
    fire_at: datetime,
    message: str,
) -> bool:
    channel = "qq"
    fp = fingerprint(event_id, fire_at, channel)
    log = session.execute(
        select(ReminderLog).where(ReminderLog.fingerprint == fp)
    ).scalar_one_or_none()
    current = datetime.now(SHANGHAI)
    if log is not None:
        if log.status == "sent":
            return False
        detail = _detail(log)
        attempts = int(detail.get("attempts", 0))
        retry_at = detail.get("next_retry_at")
        if attempts >= MAX_ATTEMPTS or (retry_at and retry_at > current.isoformat()):
            return False
    else:
        log = ReminderLog(
            id=str(uuid.uuid4()),
            todo_id=todo_id,
            fire_at=fire_at.isoformat(),
            fingerprint=fp,
            channel=channel,
            status="pending",
            detail=json.dumps({"attempts": 0}, ensure_ascii=False),
            created_at=now_iso(),
        )
        session.add(log)
        session.flush()
        detail = {}
        attempts = 0

    try:
        send_private_message(settings, message)
    except Exception as exc:  # 通道失败要记账，不能阻断其它待办。
        attempts += 1
        next_retry = current + RETRY_DELAYS[attempts - 1] if attempts <= len(RETRY_DELAYS) else None
        log.status = "failed"
        log.detail = json.dumps(
            {
                "attempts": attempts,
                "error": str(exc)[:300],
                "next_retry_at": next_retry.isoformat() if next_retry else None,
            },
            ensure_ascii=False,
        )
        session.flush()
        return False
    log.status = "sent"
    log.detail = json.dumps({"attempts": attempts + 1}, ensure_ascii=False)
    session.flush()
    return True


def _send_event(
    session: Session, settings: Settings, todo: Todo, course_name: str, event: ReminderEvent
) -> bool:
    return _send_message(
        session,
        settings,
        event_id=todo.id,
        todo_id=todo.id,
        fire_at=event.fire_at,
        message=reminder_message(todo, course_name, event.offset),
    )


def _send_class_event(session: Session, settings: Settings, event: ClassReminderEvent) -> bool:
    room = f"\n地点：{event.room}" if event.room else ""
    return _send_message(
        session,
        settings,
        event_id=event.event_id,
        todo_id=None,
        fire_at=event.fire_at,
        message=f"超课表上课提醒\n{event.course_name}{room}\n15 分钟后开始。",
    )


def run_tick() -> int:
    """调度器每 60 秒调用一次；返回本轮发送数。"""
    settings = get_settings()
    if not settings.qq_enabled or settings.qq_target_user_id <= 0:
        return 0
    sent = 0
    with session_scope(get_engine()) as session:
        config = load_config(session)
        todos = (
            session.execute(
                select(Todo).where(
                    Todo.status == "0", Todo.deleted_at.is_(None), Todo.due_at.is_not(None)
                )
            )
            .scalars()
            .all()
        )
        courses = {
            course.id: course.name for course in session.execute(select(Course)).scalars().all()
        }
        current = datetime.now(SHANGHAI)
        for todo in todos:
            if not channel_enabled_for(todo, config, "qq"):
                continue
            for event in calculate_events(todo, config):
                if event.fire_at > current or event.fire_at < current - TICK_GRACE:
                    continue
                sent += int(
                    _send_event(
                        session, settings, todo, courses.get(todo.course_id or "", ""), event
                    )
                )
        if "qq" in config.get("channels", {}).get("class", []):
            for class_event in calculate_class_events(session, config, now=current):
                if class_event.fire_at > current or class_event.fire_at < current - TICK_GRACE:
                    continue
                sent += int(_send_class_event(session, settings, class_event))
    return sent


def build_daily_summary(session: Session, current: datetime | None = None) -> str:
    """生成固定三段式摘要：今日课程、今日到期、逾期。"""
    now = (current or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    today = now.date()
    terms = session.execute(select(Term).where(Term.deleted_at.is_(None))).scalars().all()
    term = next((item for item in terms if item.is_current == 1), terms[0] if terms else None)
    courses = {course.id: course for course in session.execute(select(Course)).scalars().all()}
    periods = {
        period.lesson_no: period for period in session.execute(select(LessonPeriod)).scalars().all()
    }
    classes: list[str] = []
    if term:
        try:
            start = date.fromisoformat(term.start_date)
            week = max(1, min((today - start).days // 7 + 1, term.weeks_total))
        except ValueError:
            week = 1
        slots = session.execute(select(CourseSlot)).scalars().all()
        for slot in slots:
            if slot.weekday != today.isoweekday() or slot.course_id not in courses:
                continue
            try:
                spec = json.loads(slot.weeks)
                ranges = spec.get("ranges", [])
                only = spec.get("only", [])
                allowed = (
                    (not ranges and not only)
                    or week in only
                    or any(a <= week <= b for a, b in ranges)
                )
                if spec.get("parity") == "odd" and week % 2 == 0:
                    allowed = False
                if spec.get("parity") == "even" and week % 2 == 1:
                    allowed = False
            except (AttributeError, json.JSONDecodeError):
                allowed = True
            if not allowed:
                continue
            start_period = periods.get(slot.start_lesson)
            end_period = periods.get(slot.end_lesson)
            time_text = (
                f"{start_period.start_time}-{end_period.end_time}"
                if start_period and end_period
                else ""
            )
            classes.append(
                f"- {time_text} {courses[slot.course_id].name} {slot.room or ''}".strip()
            )
    todos = (
        session.execute(select(Todo).where(Todo.deleted_at.is_(None), Todo.status == "0"))
        .scalars()
        .all()
    )
    due_today: list[str] = []
    overdue: list[str] = []
    for todo in todos:
        if not todo.due_at:
            continue
        due = due_datetime(todo.due_at, todo.due_all_day)
        if not due:
            continue
        if due.date() == today:
            due_today.append(f"- {todo.title}")
        elif due < now:
            overdue.append(f"- {todo.title}")

    def section(title: str, values: list[str]) -> list[str]:
        return [title, *(values or ["- 无"])]

    return "\n".join(
        section("今日课程", classes) + section("今日到期", due_today) + section("逾期", overdue)
    )[:500]


def run_daily_summary() -> bool:
    settings = get_settings()
    if not settings.qq_enabled or settings.qq_target_user_id <= 0:
        return False
    with session_scope(get_engine()) as session:
        config = load_config(session)
        summary = config.get("daily_summary", {})
        if not summary.get("enabled", True) or "qq" not in config.get("channels", {}).get(
            "summary", []
        ):
            return False
        today = datetime.now(SHANGHAI).date().isoformat()
        fp = hashlib.sha256(f"daily-summary|{today}|qq".encode()).hexdigest()
        if session.execute(
            select(ReminderLog).where(ReminderLog.fingerprint == fp)
        ).scalar_one_or_none():
            return False
        summary_time = _summary_time(config)
        log = ReminderLog(
            id=str(uuid.uuid4()),
            todo_id=None,
            fire_at=f"{today}T{summary_time}:00+08:00",
            fingerprint=fp,
            channel="qq",
            status="pending",
            detail=json.dumps({"attempts": 0}),
            created_at=now_iso(),
        )
        session.add(log)
        session.flush()
        try:
            send_private_message(settings, build_daily_summary(session))
            log.status = "sent"
            log.detail = json.dumps({"attempts": 1})
            return True
        except Exception as exc:
            log.status = "failed"
            log.detail = json.dumps({"attempts": 1, "error": str(exc)[:300]}, ensure_ascii=False)
            return False


_scheduler: BackgroundScheduler | None = None


def scheduler_ok() -> bool:
    return bool(_scheduler and _scheduler.running)


def _summary_time(config: dict[str, Any]) -> str:
    raw = str(config.get("daily_summary", {}).get("time", "07:30"))
    try:
        hour, minute = (int(value) for value in raw.split(":", 1))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, TypeError):
        hour, minute = 7, 30
    return f"{hour:02d}:{minute:02d}"


def _summary_trigger(config: dict[str, Any]) -> CronTrigger:
    hour, minute = (int(value) for value in _summary_time(config).split(":"))
    return CronTrigger(hour=hour, minute=minute, timezone=SHANGHAI)


def refresh_daily_summary_schedule(config: dict[str, Any] | None = None) -> None:
    """兼容旧同步调用；M5 已移除每日摘要调度。"""
    return


def start_scheduler() -> None:
    global _scheduler
    if scheduler_ok():
        return
    scheduler = BackgroundScheduler(timezone=SHANGHAI)
    scheduler.add_job(
        run_tick,
        "interval",
        seconds=60,
        id="reminder-tick",
        replace_existing=True,
        next_run_time=datetime.now(SHANGHAI) + timedelta(seconds=1),
    )
    scheduler.start()
    _scheduler = scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
