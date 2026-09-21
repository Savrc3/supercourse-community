"""/api/health 与 /api/version 冒烟测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_ok(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["version"]
    # 迁移建表后 db 文件非空。
    assert body["db_bytes"] > 0
    assert body["media_bytes"] == 0


def test_version_lists_all_platforms(client: TestClient) -> None:
    resp = client.get("/api/version")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"api", "web", "android", "android_url", "desktop", "desktop_url"}
    assert body["web"] == body["api"]
    assert body["android"] == body["api"]
    assert body["desktop"] == body["api"]


def test_health_hides_storage_details_when_public_details_are_disabled(client: TestClient) -> None:
    from app.core.config import get_settings

    get_settings().expose_health_details = False
    body = client.get("/api/health").json()
    assert body == {"ok": True, "version": body["version"]}


def test_lifespan_created_media_dir(client: TestClient) -> None:
    from app.core.config import get_settings

    assert get_settings().media_dir.is_dir()
