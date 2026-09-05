"""系统基线数据 seed：默认作息表（附录 A 定稿）。

幂等：已存在对应 semester 的 lesson_period 则不重复插入。
作息表是小节级系统默认值，属于"设置 → 作息"的可编辑基线，
因此放在 seed 里而非迁移（迁移只建结构，不塞业务数据）。
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import delete, inspect, select
from sqlalchemy.orm import Session

from app.core.db import make_engine, session_scope
from app.core.journal import next_rev, now_iso
from app.importers.weeks import parse_weeks_expression, weeks_to_json
from app.models import Course, CourseSlot, LessonPeriod, Term

# 默认作息表：小节号 → (上课, 下课, 所属大节)。来源：需求文档附录 A。
DEFAULT_LESSON_PERIODS: list[tuple[int, str, str, int]] = [
    (1, "08:00", "08:50", 1),
    (2, "09:00", "09:50", 1),
    (3, "10:10", "11:00", 2),
    (4, "11:10", "12:00", 2),
    (5, "14:00", "14:50", 3),
    (6, "15:00", "15:50", 3),
    (7, "16:10", "17:00", 4),
    (8, "17:10", "18:00", 4),
    (9, "19:00", "19:50", 5),
    (10, "20:00", "20:50", 5),
    (11, "21:00", "21:50", 5),
]


@contextmanager
def _seed_session() -> Iterator[Session]:
    engine = make_engine()
    _ensure_schema(engine)
    with session_scope(engine) as session:
        yield session


def _ensure_schema(engine: Any) -> None:
    """首次空库自动跑迁移，保证 seed 可直连。"""
    from alembic import command
    from alembic.config import Config

    if "lesson_period" in inspect(engine).get_table_names():
        return
    here = Path(__file__).resolve().parent.parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "alembic"))
    command.upgrade(cfg, "head")


def seed_lesson_periods(session: Session, term_id: str) -> int:
    """为指定学期写入默认作息表，幂等。返回插入条数。"""
    existing = (
        session.execute(select(LessonPeriod).where(LessonPeriod.term_id == term_id)).scalars().all()
    )
    if existing:
        return 0
    for lesson_no, start, end, big in DEFAULT_LESSON_PERIODS:
        session.add(
            LessonPeriod(
                id=str(uuid.uuid4()),
                rev=next_rev(session),
                updated_at=now_iso(),
                deleted_at=None,
                term_id=term_id,
                lesson_no=lesson_no,
                start_time=start,
                end_time=end,
                big_period=big,
            )
        )
    session.flush()
    return len(DEFAULT_LESSON_PERIODS)


def seed_demo(session: Session, name: str = "2026-2027-1") -> str:
    """注入默认作息表 + 一个示例学期。返回 term_id。"""
    term = session.execute(select(Term).where(Term.name == name)).scalar_one_or_none()
    if term is None:
        term = Term(
            id=str(uuid.uuid4()),
            rev=next_rev(session),
            updated_at=now_iso(),
            deleted_at=None,
            name=name,
            label="演示学期",
            start_date="2026-08-31",
            weeks_total=20,
            is_current=1,
            archived_at=None,
        )
        session.add(term)
        session.flush()
    else:
        # 旧版演示数据曾把第一周写成 2026-09-07；演示学期实际从 8 月 31 日开始。
        if term.start_date == "2026-09-07":
            term.start_date = "2026-08-31"
            term.rev = next_rev(session)
            term.updated_at = now_iso()

        # 诊断 CRUD 时留下的测试课程不属于演示课表，保留同步墓碑但不再显示。
        diagnostic_courses = (
            session.execute(
                select(Course).where(
                    Course.term_id == term.id,
                    Course.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for course in diagnostic_courses:
            if not course.name.startswith("__诊断课程_"):
                continue
            slots = (
                session.execute(
                    select(CourseSlot).where(
                        CourseSlot.course_id == course.id,
                        CourseSlot.deleted_at.is_(None),
                    )
                )
                .scalars()
                .all()
            )
            for slot in slots:
                slot.deleted_at = now_iso()
                slot.rev = next_rev(session)
                slot.updated_at = now_iso()
            course.deleted_at = now_iso()
            course.rev = next_rev(session)
            course.updated_at = now_iso()
    seed_lesson_periods(session, term.id)
    return term.id


def seed_courses_from_mock(
    session: Session,
    term_id: str,
    mock_path: Path,
) -> int:
    """从 design-proto mock-data.json 注入演示课程（幂等）。

    用周次解析器把教师可读周次转成 weeks JSON。同门课按 name 合并为一个 course。
    返回插入的 course_slot 数。
    """
    # 幂等：先清空该 term 已有的 course（及其 slot），再按 mock 重新注入。
    old_course_ids = (
        session.execute(select(Course.id).where(Course.term_id == term_id)).scalars().all()
    )
    if old_course_ids:
        session.execute(delete(CourseSlot).where(CourseSlot.course_id.in_(old_course_ids)))
        session.execute(delete(Course).where(Course.id.in_(old_course_ids)))
        session.flush()

    records = json.loads(mock_path.read_text(encoding="utf-8"))
    course_ids: dict[str, str] = {}
    merged_slots = 0
    for i, rec in enumerate(records):
        weekday = int(rec.get("day", 1))
        start = int(rec.get("start", 1))
        end = int(rec.get("end", start))
        name = str(rec.get("name", "")).strip()
        teacher = str(rec.get("teacher", "")).strip()
        room = str(rec.get("room", "")).strip()
        if not name or room.startswith("第"):
            continue  # 跳过脏数据（room 被误写成了周次）
        spec, _ = parse_weeks_expression(str(rec.get("weeks", "")))
        weeks_json = weeks_to_json(spec)

        course_id = course_ids.get(name)
        if course_id is None:
            course_id = str(uuid.uuid4())
            course_ids[name] = course_id
            session.add(
                Course(
                    id=course_id,
                    rev=next_rev(session),
                    updated_at=now_iso(),
                    deleted_at=None,
                    term_id=term_id,
                    name=name,
                    short_name=name[:6],
                    teacher=teacher or None,
                    color=(i % 8),
                    sort_order=i,
                )
            )
        session.add(
            CourseSlot(
                id=str(uuid.uuid4()),
                rev=next_rev(session),
                updated_at=now_iso(),
                deleted_at=None,
                course_id=course_id,
                weekday=weekday,
                start_lesson=start,
                end_lesson=end,
                room=room or None,
                weeks=weeks_json,
            )
        )
        merged_slots += 1
    session.flush()
    return merged_slots


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    demo = "--demo" in argv
    mock = "--mock" in argv
    with _seed_session() as session:
        term_id = seed_demo(session)
        slots = 0
        if mock:
            root = Path(__file__).resolve().parent.parent.parent
            mock_path = root / "docs" / "design-proto" / "mock-data.json"
            if mock_path.exists():
                slots = seed_courses_from_mock(session, term_id, mock_path)
        if demo:
            print(
                f"seed done: term={term_id}, "
                f"lesson_periods={len(DEFAULT_LESSON_PERIODS)}, course_slots={slots}"
            )
        else:
            print(f"seed done: lesson_periods={len(DEFAULT_LESSON_PERIODS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
