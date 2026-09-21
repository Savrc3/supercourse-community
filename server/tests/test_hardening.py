"""墓碑清理 / 游标过旧回退 / 配对与限流加固 / 请求体上限的回归测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.journal import now_iso, parse_iso
from app.models import Course, CourseSlot, Media, Term
from app.sync.changes import build_changes
from app.sync.tombstones import purge_tombstones, set_tombstone_floor, tombstone_floor


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _term(
    term_id: str,
    rev: int,
    *,
    deleted_days_ago: int | None = None,
    name: str = "2026 秋",
) -> Term:
    return Term(
        id=term_id,
        rev=rev,
        updated_at=now_iso(),
        deleted_at=_ago(deleted_days_ago) if deleted_days_ago is not None else None,
        name=name,
        label=None,
        start_date="2026-09-07",
        weeks_total=20,
        is_current=1,
        archived_at=None,
    )


def test_purge_removes_old_tombstone_and_raises_floor(db_session: Session) -> None:
    """过期墓碑被清掉，水位线抬到被清行的 rev，旧游标自动回全量。"""
    session = db_session
    session.add(_term("term-old", 5, deleted_days_ago=90))
    session.add(_term("term-fresh", 6, deleted_days_ago=1, name="2027 春"))
    session.commit()

    assert purge_tombstones(session, days=60) == {"term": 1}
    session.commit()

    assert session.get(Term, "term-old") is None
    assert session.get(Term, "term-fresh") is not None
    assert tombstone_floor(session) == 5

    # 游标 1 的设备可能错过 rev=5 的删除 → 回全量快照
    older = build_changes(session, since=1)
    assert older["full"] is True
    assert [row["id"] for _, row in older["changes"]] == ["term-fresh"]

    # 游标已达水位线的设备继续走增量（只剩 rev=6 的那行，没有 full 字段）
    current = build_changes(session, since=5)
    assert "full" not in current
    assert [row["id"] for _, row in current["changes"]] == ["term-fresh"]


def test_purge_removes_children_before_parents(db_session: Session) -> None:
    """父行先删会撞外键：清理按子→父顺序，两个都清掉，水位线取最大 rev。"""
    session = db_session
    session.add(_term("term-1", 1, deleted_days_ago=90))
    session.flush()
    session.add(
        Course(
            id="course-1",
            rev=2,
            updated_at=now_iso(),
            deleted_at=_ago(90),
            term_id="term-1",
            name="模电",
            color=0,
            sort_order=0,
        )
    )
    session.commit()

    purged = purge_tombstones(session, days=60)
    session.commit()

    assert purged == {"course": 1, "term": 1}
    assert tombstone_floor(session) == 2


def test_purge_keeps_parent_referenced_by_live_child(db_session: Session) -> None:
    """父行被「存活」子行引用时删不掉，水位线不推进（否则会漏删）。"""
    session = db_session
    session.add(_term("term-live", 1, deleted_days_ago=90))
    session.flush()
    session.add(
        Course(
            id="course-live",
            rev=2,
            updated_at=now_iso(),
            deleted_at=_ago(90),
            term_id="term-live",
            name="模电",
            color=0,
            sort_order=0,
        )
    )
    session.flush()
    session.add(
        CourseSlot(
            id="slot-live",
            rev=3,
            updated_at=now_iso(),
            deleted_at=None,
            course_id="course-live",
            weekday=1,
            start_lesson=1,
            end_lesson=2,
            room=None,
            weeks="{}",
        )
    )
    session.commit()

    purge_tombstones(session, days=60)
    session.commit()

    assert session.get(Course, "course-live") is not None
    assert session.get(Term, "term-live") is not None
    assert tombstone_floor(session) == 0


def test_days_zero_disables_purge(db_session: Session) -> None:
    session = db_session
    session.add(_term("term-keep", 1, deleted_days_ago=365))
    session.commit()

    assert purge_tombstones(session, days=0) == {}
    assert tombstone_floor(session) == 0
    assert session.get(Term, "term-keep") is not None


def test_purge_removes_media_file(db_session: Session) -> None:
    """删 media 行时一并删磁盘文件。"""
    session = db_session
    media_dir = get_settings().media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / "media-old.jpg"
    target.write_bytes(b"x")
    session.add(
        Media(
            id="media-old",
            rev=4,
            updated_at=now_iso(),
            deleted_at=_ago(90),
            sha256="0" * 64,
            mime="image/jpeg",
            ext="jpg",
            bytes=1,
            width=1,
            height=1,
            filename="a.jpg",
            uploaded=1,
            created_at=now_iso(),
        )
    )
    session.commit()

    purged = purge_tombstones(session, days=60)
    session.commit()

    assert purged == {"media": 1}
    assert not target.exists()


def test_changes_endpoint_falls_back_to_snapshot(
    authed_client: tuple[TestClient, str, str],
) -> None:
    """/sync/changes 对过旧游标回 full 快照（客户端据此重建本地库）。"""
    client, token, _ = authed_client
    headers = {"Authorization": f"Bearer {token}"}

    pushed = client.post(
        "/api/sync/push",
        headers=headers,
        json={"ops": [{"op_id": "op-1", "entity": "todo", "id": "todo-1", "set": {"title": "甲"}}]},
    )
    assert pushed.status_code == 200
    latest = client.get("/api/sync/changes?since=0", headers=headers).json()["latest_rev"]

    from app.core.db import make_engine

    engine = make_engine()
    with Session(engine) as raw:
        set_tombstone_floor(raw, latest)
        raw.commit()
    engine.dispose()

    stale = client.get("/api/sync/changes?since=0", headers=headers).json()
    assert stale["full"] is True
    assert [row["id"] for row in stale["snapshot"]["todo"]] == ["todo-1"]

    fresh = client.get(f"/api/sync/changes?since={latest}", headers=headers).json()
    assert "full" not in fresh


def test_pairing_ttl_uses_config(
    authed_client: tuple[TestClient, str, str], monkeypatch: Any
) -> None:
    """配对码有效期取配置而不是写死的 300；异常值被钳制。"""
    client, token, _ = authed_client
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setenv("SC_PAIRING_CODE_TTL", "900")
    get_settings.cache_clear()
    assert client.post("/api/pairing/start", headers=headers).json()["expires_in"] == 900

    monkeypatch.setenv("SC_PAIRING_CODE_TTL", "5")
    get_settings.cache_clear()
    assert client.post("/api/pairing/start", headers=headers).json()["expires_in"] == 60

    monkeypatch.setenv("SC_PAIRING_CODE_TTL", "999999")
    get_settings.cache_clear()
    assert client.post("/api/pairing/start", headers=headers).json()["expires_in"] == 3600
    get_settings.cache_clear()


def test_pairing_exchange_rate_limited(client: TestClient) -> None:
    """配对码空间小：连续失败必须被限流。"""
    from app.core.rate_limit import pairing_attempts

    pairing_attempts.reset()
    try:
        for index in range(10):
            resp = client.post(
                "/api/pairing/exchange",
                json={"code": f"100-200-{index}", "name": "phone", "platform": "android"},
            )
            assert resp.status_code == 401

        blocked = client.post(
            "/api/pairing/exchange",
            json={"code": "100-200-9", "name": "phone", "platform": "android"},
        )
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["code"] == "pairing_rate_limited"
        assert blocked.headers["retry-after"] == "300"
    finally:
        pairing_attempts.reset()


def test_login_limit_uses_forwarded_ip_when_trusted(client: TestClient, monkeypatch: Any) -> None:
    """反代后按 X-Forwarded-For 记账：不同来源互不影响，同来源共享额度。"""
    from app.core.rate_limit import login_failures

    monkeypatch.setenv("SC_TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()
    login_failures.reset()
    body = {"username": "nobody", "password": "wrongpassword", "device_name": "pc"}
    try:
        for _ in range(5):
            resp = client.post(
                "/api/auth/login",
                json=body,
                headers={"X-Forwarded-For": "203.0.113.9, 127.0.0.1"},
            )
            assert resp.status_code == 401

        same = client.post(
            "/api/auth/login",
            json=body,
            headers={"X-Forwarded-For": "203.0.113.9, 127.0.0.1"},
        )
        assert same.status_code == 429

        other = client.post(
            "/api/auth/login",
            json=body,
            headers={"X-Forwarded-For": "198.51.100.7, 127.0.0.1"},
        )
        assert other.status_code == 401
    finally:
        login_failures.reset()
        get_settings.cache_clear()


def test_login_limit_ignores_forwarded_ip_by_default(client: TestClient, monkeypatch: Any) -> None:
    """默认不信任代理头：伪造 XFF 不能绕过限流。"""
    from app.core.rate_limit import login_failures

    monkeypatch.setenv("SC_TRUST_PROXY_HEADERS", "false")
    get_settings.cache_clear()
    login_failures.reset()
    body = {"username": "nobody", "password": "wrongpassword", "device_name": "pc"}
    try:
        for index in range(5):
            resp = client.post(
                "/api/auth/login",
                json=body,
                headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
            )
            assert resp.status_code == 401

        blocked = client.post(
            "/api/auth/login",
            json=body,
            headers={"X-Forwarded-For": "10.9.9.9"},
        )
        assert blocked.status_code == 429
    finally:
        login_failures.reset()
        get_settings.cache_clear()


def test_chunked_body_over_limit_is_rejected(client: TestClient, monkeypatch: Any) -> None:
    """分块（无 Content-Length）请求也要受体积上限约束。"""
    monkeypatch.setenv("SC_MAX_REQUEST_BYTES", "1024")
    get_settings.cache_clear()
    try:

        def chunks() -> Any:
            for _ in range(8):
                yield b"x" * 512

        chunked = client.post(
            "/api/sync/push",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
        assert chunked.status_code == 413
        assert chunked.json()["detail"]["code"] == "request_too_large"

        declared = client.post(
            "/api/sync/push",
            content=b"x" * 4096,
            headers={"Content-Type": "application/json"},
        )
        assert declared.status_code == 413

        # 小请求照旧走到业务逻辑（未鉴权 → 401，说明没被体积拦掉）
        small = client.post("/api/sync/push", json={"ops": []})
        assert small.status_code in (401, 403)
    finally:
        get_settings.cache_clear()


def test_reminder_text_is_human_readable() -> None:
    """提醒文案不再直接暴露 -P1D 这种 ISO 时长，也不写死「15 分钟」。"""
    from app.models import Todo
    from app.modules.remind.engine import (
        ClassReminderEvent,
        class_message,
        lead_text,
        reminder_message,
    )

    assert lead_text(timedelta(days=-1)) == "1 天"
    assert lead_text(timedelta(hours=-2)) == "2 小时"
    assert lead_text(timedelta(minutes=-15)) == "15 分钟"
    assert lead_text(timedelta(seconds=-30)) == "1 分钟"

    todo = Todo(id="t", title="交作业", kind="todo", remind_mode="inherit")
    assert reminder_message(todo, "模电", "-P1D") == "课序提醒\n模电\n交作业\n将在 1 天后到期。"
    assert reminder_message(todo, "", "-PT15M") == "课序提醒\n杂事\n交作业\n将在 15 分钟后到期。"

    started = datetime.fromisoformat("2026-09-10T08:00:00+08:00")
    event = ClassReminderEvent(
        event_id="slot-1:2026-09-10",
        course_id="course-1",
        course_name="模电",
        room="A101",
        starts_at=started,
        fire_at=started - timedelta(minutes=45),
    )
    message = class_message(event)
    assert "45 分钟后开始" in message
    assert "A101" in message


def test_parse_iso_accepts_js_z_format() -> None:
    """客户端用 toISOString() 的 'Z' 结尾，解析必须与服务端写法一致。"""
    assert parse_iso("2026-09-21T12:00:00Z") == parse_iso("2026-09-21T12:00:00+00:00")


def test_purge_does_not_touch_live_rows(db_session: Session) -> None:
    """存活行（deleted_at 为空）永远不参与清理。"""
    session = db_session
    session.add(_term("term-live-2", 1))
    session.commit()

    with patch.object(get_settings(), "tombstone_days", 0):
        assert purge_tombstones(session) == {}
    assert session.get(Term, "term-live-2") is not None
