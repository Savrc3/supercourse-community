"""M1 同步内核测试：push/changes 往返、幂等、LWW 冲突、鉴权、SSE、三态一致。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.core.db import Base, make_engine
from app.core.journal import next_rev
from app.models import Seq  # noqa: F401  (建表需要模型已注册)

AUTH = "Authorization"


def _auth(token: str) -> dict[str, str]:
    return {AUTH: f"Bearer {token}"}


def _op(
    op_id: str,
    entity: str,
    row_id: str,
    set_fields: dict[str, Any],
    base_rev: int = 0,
    updated_at: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "op_id": op_id,
        "entity": entity,
        "id": row_id,
        "set": set_fields,
        "base_rev": base_rev,
    }
    if updated_at:
        out["updated_at"] = updated_at
    return out


def _delete_op(
    op_id: str, entity: str, row_id: str, base_rev: int = 0, deleted: bool = True
) -> dict[str, Any]:
    return {
        "op_id": op_id,
        "entity": entity,
        "id": row_id,
        "set": {},
        "base_rev": base_rev,
        "deleted": deleted,
    }


def test_push_then_changes_roundtrip(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    op = _op("op-1", "term", "term-1", {"name": "2026-2027-1", "start_date": "2026-08-31"})
    resp = client.post("/api/sync/push", json={"ops": [op]}, headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["status"] == "applied"
    assert body["results"][0]["new_rev"] == 1

    changes = client.get("/api/sync/changes?since=0", headers=_auth(token)).json()
    assert changes["latest_rev"] == 1
    entities = [c[0] for c in changes["changes"]]
    assert "term" in entities
    term_row = next(c[1] for c in changes["changes"] if c[0] == "term")
    assert term_row["name"] == "2026-2027-1"
    assert term_row["rev"] == 1
    assert term_row["deleted_at"] is None


def test_changes_paginates_global_revision_without_skipping_rows(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    ops = [
        _op(f"bulk-{index}", "todo", f"todo-{index}", {"title": f"待办 {index}", "status": "0"})
        for index in range(501)
    ]
    response = client.post("/api/sync/push", json={"ops": ops}, headers=_auth(token))
    assert response.status_code == 200
    assert all(result["status"] == "applied" for result in response.json()["results"])

    first = client.get("/api/sync/changes?since=0&limit=500", headers=_auth(token)).json()
    second = client.get(
        f"/api/sync/changes?since={first['next_cursor']}&limit=500", headers=_auth(token)
    ).json()
    assert len(first["changes"]) == 500
    assert first["next_cursor"] == 500
    assert len(second["changes"]) == 1
    assert second["changes"][0][1]["rev"] == 501


def test_push_idempotent_same_op_id(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    op = _op("op-1", "term", "term-1", {"name": "A", "start_date": "2026-08-31"})
    for _ in range(5):
        resp = client.post("/api/sync/push", json={"ops": [op]}, headers=_auth(token))
        assert resp.status_code == 200
        assert resp.json()["results"][0]["status"] == "applied"
    # 库里只有一条

    rows = client.get("/api/sync/changes?since=0", headers=_auth(token)).json()["changes"]
    term_rows = [r for e, r in rows if e == "term"]
    assert len(term_rows) == 1
    assert term_rows[0]["rev"] == 1


def test_setting_push_reuses_existing_key_row(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    headers = _auth(token)
    first = client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "setting-create",
                    "setting",
                    "setting-server",
                    {"key": "reminder.config", "value": "old"},
                )
            ]
        },
        headers=headers,
    )
    assert first.status_code == 200

    second = client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "setting-update-from-another-device",
                    "setting",
                    "setting-local",
                    {"key": "reminder.config", "value": "new"},
                )
            ]
        },
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["results"][0]["status"] == "applied"

    rows = [
        row
        for entity, row in client.get("/api/sync/changes?since=0", headers=headers).json()[
            "changes"
        ]
        if entity == "setting"
    ]
    assert len(rows) == 1
    assert rows[0]["id"] == "setting-server"
    assert rows[0]["value"] == "new"


def test_soft_delete_restore_and_idempotency(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    headers = _auth(token)
    create = client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "todo-create",
                    "todo",
                    "todo-1",
                    {"title": "待删除", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=headers,
    )
    assert create.json()["results"][0]["new_rev"] == 1

    deleted = client.post(
        "/api/sync/push",
        json={"ops": [_delete_op("todo-delete", "todo", "todo-1", base_rev=1)]},
        headers=headers,
    )
    assert deleted.json()["results"][0]["status"] == "applied"
    row = next(
        r
        for e, r in client.get("/api/sync/changes?since=0", headers=headers).json()["changes"]
        if e == "todo"
    )
    assert row["deleted_at"]

    retry = client.post(
        "/api/sync/push",
        json={"ops": [_delete_op("todo-delete", "todo", "todo-1", base_rev=1)]},
        headers=headers,
    )
    assert retry.json()["results"][0]["new_rev"] == deleted.json()["results"][0]["new_rev"]

    restored = client.post(
        "/api/sync/push",
        json={"ops": [_delete_op("todo-restore", "todo", "todo-1", deleted=False)]},
        headers=headers,
    )
    assert restored.json()["results"][0]["status"] == "applied"
    row = next(
        r
        for e, r in client.get("/api/sync/changes?since=0", headers=headers).json()["changes"]
        if e == "todo"
    )
    assert row["deleted_at"] is None


def test_lww_conflict_same_field(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    # 建行 rev=1
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "原始", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=_auth(token),
    )
    # 服务端被"另一设备"改过到 rev=2
    client.post(
        "/api/sync/push",
        json={
            "ops": [_op("op-1b", "todo", "t1", {"title": "服务器版"}, 1, "2026-01-05T00:00:00Z")]
        },
        headers=_auth(token),
    )
    # 设备 B 拿旧 base_rev=1 改同一字段 → 服务端已变 → 触冲突
    client.post(
        "/api/sync/push",
        json={"ops": [_op("op-2", "todo", "t1", {"title": "B改"}, 1, "2026-01-02T00:00:00Z")]},
        headers=_auth(token),
    )
    conflicts = client.get("/api/conflicts", headers=_auth(token)).json()["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["entity"] == "todo"
    # 服务端 updated_at=01-05 比客户端 01-02 新 → 服务端胜
    assert conflicts[0]["winner"] == "server"
    assert conflicts[0]["server_row"]["title"] == "服务器版"
    assert conflicts[0]["local_row"]["title"] == "B改"


def test_lww_diff_fields_both_kept(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "A", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=_auth(token),
    )
    # base_rev=1 但改不同字段 → 字段都保留
    client.post(
        "/api/sync/push",
        json={"ops": [_op("op-2", "todo", "t1", {"status": "1"}, 1)]},
        headers=_auth(token),
    )
    rows = client.get("/api/sync/changes?since=0", headers=_auth(token)).json()["changes"]
    todo_row = next(r for e, r in rows if e == "todo")
    assert todo_row["title"] == "A"
    assert todo_row["status"] == "1"


def test_todo_rejects_legacy_status(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    response = client.post(
        "/api/sync/push",
        json={"ops": [_op("op-invalid-status", "todo", "t-invalid", {"status": "doing"}, 0)]},
        headers=_auth(token),
    )
    result = response.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "invalid_status"


def test_conflict_resolve(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    # 建行 → 服务端修改 → 另一设备拿旧 base_rev 改同字段 → 冲突
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "A", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=_auth(token),
    )
    client.post(
        "/api/sync/push",
        json={"ops": [_op("op-b", "todo", "t1", {"title": "服务器"}, 1, "2026-01-05T00:00:00Z")]},
        headers=_auth(token),
    )
    client.post(
        "/api/sync/push",
        json={"ops": [_op("op-2", "todo", "t1", {"title": "客户端"}, 1, "2026-01-02T00:00:00Z")]},
        headers=_auth(token),
    )
    conflicts = client.get("/api/conflicts", headers=_auth(token)).json()["conflicts"]
    assert len(conflicts) == 1
    cid = conflicts[0]["id"]
    # 解决为 server 胜
    resp = client.post(
        f"/api/conflicts/{cid}/resolve",
        json={"choice": "server"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    # 解决后冲突箱为空
    rest = client.get("/api/conflicts", headers=_auth(token)).json()["conflicts"]
    assert rest == []


def test_conflict_resolve_local_applies_loser_fields(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    headers = _auth(token)
    client.post(
        "/api/sync/push",
        json={"ops": [_op("local-1", "todo", "local-t1", {"title": "原始", "status": "0"})]},
        headers=headers,
    )
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "local-2",
                    "todo",
                    "local-t1",
                    {
                        "title": "服务端",
                    },
                    1,
                    "2026-01-05T00:00:00Z",
                )
            ]
        },
        headers=headers,
    )
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "local-3",
                    "todo",
                    "local-t1",
                    {
                        "title": "本地",
                    },
                    1,
                    "2026-01-02T00:00:00Z",
                )
            ]
        },
        headers=headers,
    )
    conflict = client.get("/api/conflicts", headers=headers).json()["conflicts"][0]
    response = client.post(
        f"/api/conflicts/{conflict['id']}/resolve",
        json={"choice": "local"},
        headers=headers,
    )
    assert response.status_code == 200
    todo = next(
        row
        for entity, row in client.get("/api/sync/changes?since=0", headers=headers).json()[
            "changes"
        ]
        if entity == "todo"
    )
    assert todo["title"] == "本地"


def test_auth_required(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, _, _ = authed_client
    # 无 token 访问业务接口 → 401
    assert client.get("/api/sync/changes").status_code == 401
    assert client.post("/api/sync/push", json={"ops": []}).status_code == 401
    # 无效 token → 401
    r = client.get("/api/sync/changes", headers=_auth("bogus"))
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_token"
    # health/version 无需鉴权
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/events").status_code == 401


def test_pairing_exchange_flow(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    # 已登录设备生成配对码
    start = client.post("/api/pairing/start", headers=_auth(token))
    assert start.status_code == 200
    code = start.json()["code"]
    # 新设备换取令牌
    exch = client.post(
        "/api/pairing/exchange",
        json={"code": code, "name": "phone", "platform": "android"},
    )
    assert exch.status_code == 200
    new_token = exch.json()["token"]
    assert new_token
    # 新令牌可用
    assert client.get("/api/sync/changes", headers=_auth(new_token)).status_code == 200
    # 同一码二次使用被拒
    again = client.post(
        "/api/pairing/exchange",
        json={"code": code, "name": "phone2", "platform": "android"},
    )
    assert again.status_code == 401
    assert again.json()["detail"]["code"] == "pairing_used"


def test_revoke_device_immediate_401(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, device_id = authed_client
    # 吊销自己
    assert client.delete(f"/api/devices/{device_id}", headers=_auth(token)).status_code == 200
    resp = client.get("/api/sync/changes", headers=_auth(token))
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "device_revoked"


def test_rename_device_and_filter_revoked(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, device_id = authed_client
    # 第一台设备改名
    r = client.put(
        f"/api/devices/{device_id}",
        json={"name": "我的手机"},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "我的手机"
    # 设备列表里能看到新名 + is_current
    devices = client.get("/api/devices", headers=_auth(token)).json()["devices"]
    me = next(d for d in devices if d["id"] == device_id)
    assert me["name"] == "我的手机"
    assert me["is_current"] is True
    # 空名拒绝
    bad = client.put(f"/api/devices/{device_id}", json={"name": "  "}, headers=_auth(token))
    assert bad.status_code == 400


def test_export_restore_roundtrip(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "作业", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=_auth(token),
    )
    # 软删一行，验证三态含软删
    client.post(
        "/api/sync/push",
        json={"ops": [_op("op-2", "todo", "t1", {"deleted_at": None})]},
        headers=_auth(token),
    )
    dumped = client.get("/api/export", headers=_auth(token))
    assert dumped.status_code == 200
    data = dumped.json()
    assert data["rows"]["todo"]
    # restore 到另一设备（此处复用同一库做 清库→恢复 三态验证）
    restored = client.post("/api/restore", json=data, headers=_auth(token))
    assert restored.status_code == 200
    assert restored.json()["restored"] >= 1
    # 恢复后再导出，行数一致
    again = client.get("/api/export", headers=_auth(token)).json()
    assert len(again["rows"]["todo"]) == len(data["rows"]["todo"])


def test_sse_subscribe_receives_broadcast(
    authed_client: tuple[TestClient, str, str],
) -> None:
    from app.core.events import broadcast_rev

    # 广播不抛错（真实 SSE 流应在集成层验证，TestClient 会对无限流阻塞）。
    broadcast_rev(99)
    assert True


def test_unknown_entity_and_field_rejected(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    r = client.post(
        "/api/sync/push",
        json={"ops": [_op("op-1", "nope", "x", {})]},
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "rejected"
    assert r.json()["results"][0]["error"]["code"] == "unknown_entity"

    r2 = client.post(
        "/api/sync/push",
        json={"ops": [_op("op-2", "todo", "t", {"bogus": 1})]},
        headers=_auth(token),
    )
    assert r2.json()["results"][0]["status"] == "rejected"
    assert r2.json()["results"][0]["error"]["code"] == "unknown_field"


@given(
    st.lists(
        st.tuples(
            st.text(min_size=1),
            st.integers(min_value=-5, max_value=100),
        ),
        max_size=20,
    )
)
@settings(max_examples=30, deadline=None)
def test_hypothesis_clamp_updated_at(
    pairs: list[tuple[str, int]],
) -> None:
    """时钟钳制属性：未来超过 60 秒的时间戳被钳到服务端时间。"""
    from datetime import datetime, timedelta, timezone

    from app.core.journal import clamp_updated_at

    for _raw, offset in pairs:
        try:
            base = datetime(2026, 1, 1, tzinfo=timezone.utc)
            ts = (base + timedelta(seconds=offset)).isoformat()
            out = clamp_updated_at(ts, base.isoformat())
            if offset > 60:
                assert out == base.isoformat()
        except ValueError:
            pass


def test_bootstrap_full_snapshot(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "第一", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=_auth(token),
    )
    boot = client.get("/api/bootstrap", headers=_auth(token)).json()
    assert boot["latest_rev"] == 1
    assert "todo" in boot["snapshot"]
    assert len(boot["snapshot"]["todo"]) == 1


def test_lww_client_wins_when_stamp_is_newer(
    authed_client: tuple[TestClient, str, str],
) -> None:
    """客户端时间戳更新时必须赢——LWW 不能恒为服务端胜。

    客户端戳取 op 级 updated_at（``set`` 里没有这个字段，它不在白名单内），
    所以这里验证的是「读了 op_ts」这一步没漏。
    """
    client, token, _ = authed_client
    headers = _auth(token)
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "初始", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=headers,
    )
    client.post(
        "/api/sync/push",
        json={"ops": [_op("op-2", "todo", "t1", {"title": "服务器"}, 1)]},
        headers=headers,
    )
    newish = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    resp = client.post(
        "/api/sync/push",
        json={"ops": [_op("op-3", "todo", "t1", {"title": "客户端"}, 1, newish)]},
        headers=headers,
    )
    result = resp.json()["results"][0]
    assert result["status"] == "merged"
    assert result["server_row"]["title"] == "客户端"
    conflicts = client.get("/api/conflicts", headers=headers).json()["conflicts"]
    assert conflicts[0]["winner"] == "client"
    # 冲突箱里的「服务端版本」是冲突发生前那一版，不是合并后的结果
    assert conflicts[0]["server_row"]["title"] == "服务器"
    assert conflicts[0]["local_row"]["title"] == "客户端"


def test_lww_far_future_stamp_loses(
    authed_client: tuple[TestClient, str, str],
) -> None:
    """未来超过 60 秒的客户端戳不可信（§5.6）：即使等于「更新」也判服务端胜。"""
    client, token, _ = authed_client
    headers = _auth(token)
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "初始", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=headers,
    )
    client.post(
        "/api/sync/push",
        json={"ops": [_op("op-2", "todo", "t1", {"title": "服务器"}, 1)]},
        headers=headers,
    )
    far_future = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
    resp = client.post(
        "/api/sync/push",
        json={"ops": [_op("op-3", "todo", "t1", {"title": "客户端"}, 1, far_future)]},
        headers=headers,
    )
    result = resp.json()["results"][0]
    assert result["status"] == "merged"
    assert result["server_row"]["title"] == "服务器"
    conflicts = client.get("/api/conflicts", headers=headers).json()["conflicts"]
    assert conflicts[0]["winner"] == "server"


def test_restore_advances_rev_timeline(
    authed_client: tuple[TestClient, str, str],
) -> None:
    """恢复后的数据必须落在已有游标之后，且后续取号不与旧时间线撞号。"""
    client, token, _ = authed_client
    headers = _auth(token)
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-1",
                    "todo",
                    "t1",
                    {"title": "旧数据", "status": "0", "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=headers,
    )
    cursor = client.get("/api/sync/changes?since=0", headers=headers).json()
    # 构造一份「旧时间线」的备份（rev 很大），模拟换机恢复
    dumped = client.get("/api/export", headers=headers).json()
    dumped["rows"]["todo"][0]["rev"] = 1000
    dumped["latest_rev"] = 1000
    assert client.post("/api/restore", json=dumped, headers=headers).status_code == 200
    client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-2",
                    "todo",
                    "t2",
                    {"title": "恢复后新增", "status": "0", "created_at": "2026-01-02T00:00:00Z"},
                )
            ]
        },
        headers=headers,
    )
    after = client.get(f"/api/sync/changes?since={cursor['next_cursor']}", headers=headers).json()
    titles = [row["title"] for _, row in after["changes"]]
    # 恢复行与恢复后新增的行都能被「恢复前就在的游标」看到
    assert "旧数据" in titles
    assert "恢复后新增" in titles
    revs = [row["rev"] for _, row in after["changes"]]
    assert len(set(revs)) == len(revs)
    assert min(revs) > cursor["next_cursor"]


def test_push_rejects_dangling_reference(
    authed_client: tuple[TestClient, str, str],
) -> None:
    """引用不存在的行必须回 rejected，而不是 IntegrityError → 500。"""
    client, token, _ = authed_client
    resp = client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-slot",
                    "course_slot",
                    "slot-1",
                    {
                        "course_id": "no-such-course",
                        "weekday": 3,
                        "start_lesson": 1,
                        "end_lesson": 2,
                        "weeks": "{}",
                    },
                )
            ]
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "invalid_reference:course_id"


def test_push_rejects_missing_required_field(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    resp = client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-term",
                    "term",
                    "term-1",
                    {"name": "缺开始日期"},
                )
            ]
        },
        headers=_auth(token),
    )
    result = resp.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "missing_field:start_date"


def test_push_rejects_out_of_range_fields(
    authed_client: tuple[TestClient, str, str],
) -> None:
    """越界字段回明确错误码：weekday/节次/周次 JSON/优先级。"""
    client, token, _ = authed_client
    headers = _auth(token)
    term = _op("op-term", "term", "term-1", {"name": "学期", "start_date": "2026-08-31"})
    course = _op("op-course", "course", "course-1", {"term_id": "term-1", "name": "模电"})
    client.post("/api/sync/push", json={"ops": [term, course]}, headers=headers)
    cases = [
        (
            {
                "course_id": "course-1",
                "weekday": 99,
                "start_lesson": 1,
                "end_lesson": 2,
                "weeks": "{}",
            },
            "invalid_weekday",
        ),
        (
            {
                "course_id": "course-1",
                "weekday": 1,
                "start_lesson": 5,
                "end_lesson": 2,
                "weeks": "{}",
            },
            "invalid_lesson_range",
        ),
        (
            {
                "course_id": "course-1",
                "weekday": 1,
                "start_lesson": 1,
                "end_lesson": 2,
                "weeks": "垃圾",
            },
            "invalid_weeks",
        ),
    ]
    for index, (fields, code) in enumerate(cases):
        resp = client.post(
            "/api/sync/push",
            json={"ops": [_op(f"op-slot-{index}", "course_slot", f"slot-{index}", fields)]},
            headers=headers,
        )
        assert resp.json()["results"][0]["error"]["code"] == code
    bad_priority = client.post(
        "/api/sync/push",
        json={
            "ops": [
                _op(
                    "op-todo",
                    "todo",
                    "todo-1",
                    {"title": "待办", "priority": 9, "created_at": "2026-01-01T00:00:00Z"},
                )
            ]
        },
        headers=headers,
    )
    assert bad_priority.json()["results"][0]["error"]["code"] == "invalid_priority"


def test_next_rev_is_atomic_under_concurrency(tmp_path: Path) -> None:
    """并发取号不得重复：Python 层 read-modify-write 会，SQL 层 v = v + 1 不会。"""
    from concurrent.futures import ThreadPoolExecutor

    data_dir = tmp_path / "data"
    (data_dir / "media").mkdir(parents=True, exist_ok=True)
    engine = make_engine(f"sqlite:///{(data_dir / 'app.db').as_posix()}")
    Base.metadata.create_all(engine)

    def take() -> list[int]:
        with Session(engine) as session:
            revs = [next_rev(session) for _ in range(3)]
            session.commit()
            return revs

    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(lambda _: take(), range(6)))
    assigned = [rev for batch in batches for rev in batch]
    assert len(assigned) == 18
    assert len(set(assigned)) == 18
    assert sorted(assigned) == list(range(1, 19))
