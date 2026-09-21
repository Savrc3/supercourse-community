"""作息表 seed 测试：默认 11 小节、5 大节、幂等。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LessonPeriod
from app.seed import seed_demo, seed_lesson_periods


def test_seed_demo_creates_term_and_periods(db_session: Session) -> None:
    term_id = seed_demo(db_session)
    assert term_id
    periods = (
        db_session.execute(select(LessonPeriod).where(LessonPeriod.term_id == term_id))
        .scalars()
        .all()
    )
    assert len(periods) == 11
    # 大节分布：第1节2小节、第2节2、第3节2、第4节2、第5节3
    bigs = [p.big_period for p in periods]
    assert bigs.count(1) == 2
    assert bigs.count(2) == 2
    assert bigs.count(3) == 2
    assert bigs.count(4) == 2
    assert bigs.count(5) == 3
    # 时间正确（第一小节）
    first = min(periods, key=lambda p: p.lesson_no)
    assert (first.lesson_no, first.start_time, first.end_time) == (1, "08:00", "08:50")


def test_seed_is_idempotent(db_session: Session) -> None:
    term_id = seed_demo(db_session)
    # 再次 seed 不重复插入
    inserted = seed_lesson_periods(db_session, term_id)
    assert inserted == 0
    count = (
        db_session.execute(select(LessonPeriod).where(LessonPeriod.term_id == term_id))
        .scalars()
        .all()
    )
    assert len(count) == 11
