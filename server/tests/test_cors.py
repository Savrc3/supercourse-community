"""桌面端本地静态服务器跨端口访问 API 的回归测试。"""

from fastapi.testclient import TestClient

from app.main import configured_origins


def test_loopback_desktop_origins_are_allowed(client: TestClient) -> None:
    for origin in ("http://127.0.0.1:4173", "http://127.0.0.1:49831"):
        response = client.options(
            "/api/auth/status",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "camera=(self)" in response.headers["permissions-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_configured_origins_are_comma_separated() -> None:
    settings = type("Settings", (), {"allowed_origins": "https://a.test, https://b.test"})()
    assert configured_origins(settings) == [
        "https://a.test",
        "https://b.test",
    ]


def test_oversized_content_length_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        headers={"Content-Length": str(21 * 1024 * 1024)},
        content=b"{}",
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_too_large"
