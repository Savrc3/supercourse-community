"""提醒时间计算回归测试。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Todo
from app.modules.remind.channels import qq
from app.modules.remind.engine import (
    DEFAULT_CONFIG,
    calculate_events,
    channel_enabled_for,
    due_datetime,
    fingerprint,
    parse_iso_duration,
)


def todo(**overrides: object) -> Todo:
    values: dict[str, object] = {
        "id": "todo-1",
        "deleted_at": None,
        "status": "0",
        "due_at": "2026-09-05",
        "due_all_day": 1,
        "kind": "todo",
        "remind_mode": "inherit",
        "remind_offsets": None,
        "title": "交作业",
    }
    values.update(overrides)
    return Todo(**values)


def test_parse_iso_duration() -> None:
    assert parse_iso_duration("-P1D").days == -1
    assert parse_iso_duration("-PT2H").total_seconds() == -7200
    assert parse_iso_duration("-PT10M").total_seconds() == -600
    assert parse_iso_duration("bad") is None


def test_all_day_uses_nine_oclock_shanghai() -> None:
    assert due_datetime("2026-09-05", 1).isoformat() == "2026-09-05T09:00:00+08:00"


def test_only_one_day_before_offset_is_calculated() -> None:
    now = datetime.fromisoformat("2026-09-04T08:00:00+08:00")
    events = calculate_events(todo(), DEFAULT_CONFIG, now=now)
    assert [event.offset for event in events] == ["-P1D"]
    assert events[0].fire_at.isoformat() == "2026-09-04T09:00:00+08:00"

    assert calculate_events(todo(remind_mode="off"), DEFAULT_CONFIG, now=now) == []


def test_off_done_and_expired_events_are_silent() -> None:
    now = datetime.fromisoformat("2026-09-05T12:00:00+08:00")
    assert calculate_events(todo(remind_mode="off"), DEFAULT_CONFIG, now=now) == []
    assert calculate_events(todo(status="1"), DEFAULT_CONFIG, now=now) == []
    assert calculate_events(todo(due_at="2026-09-01"), DEFAULT_CONFIG, now=now) == []


def test_fingerprint_includes_event_and_channel() -> None:
    when = datetime.fromisoformat("2026-09-05T09:00:00+08:00")
    assert fingerprint("todo-1", when, "qq") != fingerprint("todo-1", when, "mobile")
    assert fingerprint("todo-1", when, "qq") != fingerprint("todo-2", when, "qq")


def test_channels_are_selected_by_todo_kind() -> None:
    config = {
        "channels": {
            "todo": [],
            "exam": ["qq"],
            "signup": [],
            "other": [],
        }
    }
    assert not channel_enabled_for(todo(kind="todo"), config, "qq")
    assert not channel_enabled_for(todo(kind="exam"), config, "qq")


def test_daily_summary_refresh_is_a_compatibility_noop() -> None:
    import app.modules.remind.engine as engine

    engine.refresh_daily_summary_schedule({})


def test_qq_channel_sends_bearer_token(monkeypatch) -> None:
    response = Mock()
    response.json.return_value = {"status": "ok", "retcode": 0}
    post = Mock(return_value=response)
    monkeypatch.setattr(qq.httpx, "post", post)

    qq.send_private_message(
        Settings(
            qq_enabled=True,
            onebot_url="http://127.0.0.1:3000",
            onebot_token="token",
            qq_target_user_id=123,
        ),
        "测试消息",
    )

    post.assert_called_once_with(
        "http://127.0.0.1:3000/send_private_msg",
        json={"user_id": 123, "message": "测试消息"},
        headers={"Authorization": "Bearer token"},
        timeout=5,
    )


def test_class_events_respect_term_range(db_session: Session) -> None:
    """学期区间外不提醒：开学前与结课后的同一天都不该冒出来。

    这里的 slot 排周四；学期 2026-09-07（周一）起、2 周（到 09-20 止）。
    以 09-03（开学前的周四）为「今天」时，56 天窗口里含 09-03、09-10、
    09-17、09-24 四个周四——只有落在学期内的两个才允许出提醒。
    """
    from app.core.journal import now_iso
    from app.models import Course, CourseSlot, LessonPeriod, Term
    from app.modules.remind.engine import calculate_class_events

    session = db_session
    session.add(
        Term(
            id="term-1",
            rev=1,
            updated_at=now_iso(),
            deleted_at=None,
            name="2026 秋",
            label=None,
            start_date="2026-09-07",
            weeks_total=2,
            is_current=1,
            archived_at=None,
        )
    )
    # 模型之间没有 relationship，flush 不做依赖排序 → 父行必须分次落库。
    session.flush()
    session.add(
        LessonPeriod(
            id="period-1",
            rev=2,
            updated_at=now_iso(),
            deleted_at=None,
            term_id="term-1",
            lesson_no=1,
            start_time="08:00",
            end_time="08:45",
            big_period=1,
        )
    )
    # 模型之间没有 relationship，flush 不做依赖排序 → 父行必须分次落库。
    session.flush()
    session.add(
        Course(
            id="course-1",
            rev=3,
            updated_at=now_iso(),
            deleted_at=None,
            term_id="term-1",
            name="模电",
            color=0,
            sort_order=0,
        )
    )
    session.add(
        CourseSlot(
            id="slot-1",
            rev=4,
            updated_at=now_iso(),
            deleted_at=None,
            course_id="course-1",
            weekday=4,
            start_lesson=1,
            end_lesson=2,
            room="A101",
            weeks="{}",
        )
    )
    session.flush()
    session.commit()

    now = datetime.fromisoformat("2026-09-03T06:00:00+08:00")
    events = calculate_class_events(session, DEFAULT_CONFIG, now=now)
    assert [event.starts_at.date().isoformat() for event in events] == ["2026-09-10", "2026-09-17"]

    # 结课后同样安静：09-21 之后的周四都超出学期区间
    after = datetime.fromisoformat("2026-09-21T06:00:00+08:00")
    assert calculate_class_events(session, DEFAULT_CONFIG, now=after) == []


def test_daily_summary_skips_soft_deleted_rows(db_session: Session) -> None:
    """今日课程摘要必须过滤软删的课程/时段（与 calculate_class_events 一致）。"""
    from app.core.journal import now_iso
    from app.models import Course, CourseSlot, LessonPeriod, Term
    from app.modules.remind.engine import build_daily_summary

    session = db_session
    session.add(
        Term(
            id="term-d",
            rev=1,
            updated_at=now_iso(),
            deleted_at=None,
            name="2026 秋",
            label=None,
            start_date="2026-09-07",
            weeks_total=4,
            is_current=1,
            archived_at=None,
        )
    )
    session.flush()
    session.add(
        LessonPeriod(
            id="period-d",
            rev=2,
            updated_at=now_iso(),
            deleted_at=None,
            term_id="term-d",
            lesson_no=1,
            start_time="08:00",
            end_time="08:45",
            big_period=1,
        )
    )
    session.flush()
    session.add(
        Course(
            id="course-d",
            rev=3,
            updated_at=now_iso(),
            deleted_at=None,
            term_id="term-d",
            name="模拟电子技术",
            color=0,
            sort_order=0,
        )
    )
    session.flush()
    session.add(
        CourseSlot(
            id="slot-d",
            rev=4,
            updated_at=now_iso(),
            deleted_at=None,
            course_id="course-d",
            weekday=4,
            start_lesson=1,
            end_lesson=1,
            room="A101",
            weeks="{}",
        )
    )
    session.commit()

    # 2026-09-10 是第 1 周的周四
    today = datetime.fromisoformat("2026-09-10T07:00:00+08:00")
    fresh = build_daily_summary(session, current=today)
    assert "模拟电子技术" in fresh
    assert "08:00-08:45" in fresh

    course = session.get(Course, "course-d")
    assert course is not None
    course.deleted_at = now_iso()
    session.commit()
    assert "模拟电子技术" not in build_daily_summary(session, current=today)

    course.deleted_at = None
    slot = session.get(CourseSlot, "slot-d")
    assert slot is not None
    slot.deleted_at = now_iso()
    session.commit()
    assert "模拟电子技术" not in build_daily_summary(session, current=today)

    slot.deleted_at = None
    period = session.get(LessonPeriod, "period-d")
    assert period is not None
    period.deleted_at = now_iso()
    session.commit()
    without_period = build_daily_summary(session, current=today)
    # 时段被删只是拿不到时间文本，课程本身照旧列出
    assert "模拟电子技术" in without_period
    assert "08:00-08:45" not in without_period


def test_custom_offsets_override_defaults() -> None:
    """remind_mode=custom 时用待办自己的提前量，按提前量从早到晚触发。"""
    now = datetime.fromisoformat("2026-09-04T00:00:00+08:00")
    events = calculate_events(
        todo(remind_mode="custom", remind_offsets='["-PT30M", "-P1D"]'),
        DEFAULT_CONFIG,
        now=now,
    )
    assert [event.offset for event in events] == ["-P1D", "-PT30M"]
    assert events[0].fire_at.isoformat() == "2026-09-04T09:00:00+08:00"
    assert events[1].fire_at.isoformat() == "2026-09-05T08:30:00+08:00"


def test_custom_offsets_fall_back_when_unusable() -> None:
    """写坏的/空的自定义提前量不能让提醒消失，必须退回全局默认。"""
    now = datetime.fromisoformat("2026-09-04T08:00:00+08:00")
    for raw in (None, "", "不是 JSON", "{}", "[]", '["bad", "P1D", 5]', '["PT1H"]'):
        events = calculate_events(
            todo(remind_mode="custom", remind_offsets=raw),
            DEFAULT_CONFIG,
            now=now,
        )
        assert [event.offset for event in events] == ["-P1D"], raw
    assert (
        calculate_events(
            todo(remind_mode="off", remind_offsets='["-P1D"]'), DEFAULT_CONFIG, now=now
        )
        == []
    )


def test_custom_offsets_dedupe_and_sort() -> None:
    now = datetime.fromisoformat("2026-09-04T00:00:00+08:00")
    events = calculate_events(
        todo(remind_mode="custom", remind_offsets='["-PT30M", "-P1D", "-PT30M", "-PT2H"]'),
        DEFAULT_CONFIG,
        now=now,
    )
    assert [event.offset for event in events] == ["-P1D", "-PT2H", "-PT30M"]
