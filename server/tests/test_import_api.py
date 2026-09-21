"""导入 API 测试：干跑 / 落库 / 重复导入无变化 / 回滚。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.fixtures_gen import build_sample_bytes, build_sample_xlsx_bytes

from app.api import importer as importer_api


def _upload(
    client: TestClient, token: str, filename: str = "sample.xls", data: bytes | None = None
):
    data = data or build_sample_bytes()
    return client.post(
        "/api/import/xls",
        files={"file": (filename, data, "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_import_dry_run_returns_draft(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    resp = _upload(client, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["draft_id"]
    assert body["term_exists"] is False
    assert body["filename"] == "sample.xls"
    assert body["expires_at"]
    assert body["semester"] == "2025-2026-2"
    assert len(body["courses"]) >= 6
    assert "added" in body["diff"]
    assert len(body["diff"]["added"]) >= 6
    assert body["diff"]["added"][0]["selected"] is True
    assert body["diff"]["added"][0]["after"]["course_name"]


def test_import_commit_uses_explicit_term_start_date(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    dry = _upload(client, token).json()
    commit = client.post(
        "/api/import/commit",
        json={
            "draft_id": dry["draft_id"],
            "accepted": list(range(len(dry["slots"]))),
            "start_date": "2026-08-31",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert commit.status_code == 200
    snapshot = client.get("/api/bootstrap", headers={"Authorization": f"Bearer {token}"}).json()[
        "snapshot"
    ]
    assert snapshot["term"][0]["start_date"] == "2026-08-31"
    assert len(snapshot["lesson_period"]) == 11
    assert len({course["color"] for course in snapshot["course"]}) > 1


def test_import_commit_rejects_invalid_term_start_date(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    dry = _upload(client, token).json()
    resp = client.post(
        "/api/import/commit",
        json={
            "draft_id": dry["draft_id"],
            "accepted": [],
            "start_date": "not-a-date",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_start_date"


def test_import_xlsx_dry_run(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    resp = _upload(client, token, "sample.xlsx", build_sample_xlsx_bytes())
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "sample.xlsx"
    assert {course["name"] for course in body["courses"]} == {"高等数学", "体育"}
    assert len(body["diff"]["added"]) == 2


def test_import_rejects_unsupported_format(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    resp = _upload(client, token, "notes.txt", b"not a timetable")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_format"


def test_import_commit_rejects_expired_draft(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    draft_id = _upload(client, token).json()["draft_id"]
    importer_api._drafts[draft_id]["created_at"] -= importer_api.DRAFT_TTL + 1
    resp = client.post(
        "/api/import/commit",
        json={"draft_id": draft_id, "accepted": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "draft_expired"


def test_import_commit_then_no_change(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    dry = _upload(client, token).json()
    # 提交全部 added
    accepted = list(range(len(dry["slots"])))
    commit = client.post(
        "/api/import/commit",
        json={"draft_id": dry["draft_id"], "accepted": accepted},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert commit.status_code == 200
    assert commit.json()["applied"] >= 6
    assert commit.json()["snapshot_done"] is True

    bootstrap = client.get(
        "/api/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert len(bootstrap["snapshot"]["course"]) == len(dry["courses"])
    assert len(bootstrap["snapshot"]["course_slot"]) == len(dry["slots"])

    # 再次上传 → 差异应为空（无变化）
    dry2 = _upload(client, token).json()
    assert dry2["diff"]["added"] == []
    assert dry2["diff"]["changed"] == []
    assert dry2["diff"]["removed"] == []


def test_import_change_updates_slot_and_remove_soft_deletes(
    authed_client: tuple[TestClient, str, str],
) -> None:
    client, token, _ = authed_client
    initial = _upload(client, token).json()
    initial_commit = client.post(
        "/api/import/commit",
        json={"draft_id": initial["draft_id"], "accepted": list(range(len(initial["slots"])))},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert initial_commit.status_code == 200

    changed = _upload(client, token, data=build_sample_bytes(primary_room="教202")).json()
    assert len(changed["diff"]["changed"]) == 1
    changed_item = changed["diff"]["changed"][0]
    changed_commit = client.post(
        "/api/import/commit",
        json={
            "draft_id": changed["draft_id"],
            "accepted": [
                {
                    "kind": changed_item["kind"],
                    "index": changed_item["index"],
                    "row_id": changed_item["row_id"],
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert changed_commit.status_code == 200

    reduced = _upload(
        client,
        token,
        data=build_sample_bytes(primary_room="教202", include_extra=False),
    ).json()
    assert reduced["diff"]["added"] == []
    assert reduced["diff"]["changed"] == []
    assert reduced["diff"]["removed"]
    removed_item = reduced["diff"]["removed"][0]
    removed_commit = client.post(
        "/api/import/commit",
        json={
            "draft_id": reduced["draft_id"],
            "accepted": [{"kind": "removed", "row_id": removed_item["row_id"]}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert removed_commit.status_code == 200

    snapshot = client.get(
        "/api/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    ).json()["snapshot"]
    slot = next(row for row in snapshot["course_slot"] if row["id"] == removed_item["row_id"])
    assert slot["deleted_at"] is not None


def test_import_rollback_restores(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    dry = _upload(client, token).json()
    commit = client.post(
        "/api/import/commit",
        json={"draft_id": dry["draft_id"], "accepted": list(range(len(dry["slots"])))},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert commit.status_code == 200
    tid = commit.json()["term_id"]
    # 回滚
    rb = client.post(
        "/api/import/rollback",
        json={"term_id": tid},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rb.status_code == 200
    assert rb.json()["ok"] is True

    restored = client.get(
        "/api/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert restored["snapshot"]["course"] == []
    assert restored["snapshot"]["course_slot"] == []
