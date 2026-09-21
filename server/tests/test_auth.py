"""账号密码入口测试：首个账号注册、错误登录和多设备登录。"""

from fastapi.testclient import TestClient

from app.core.rate_limit import login_failures


def test_first_account_register_and_login(client: TestClient) -> None:
    assert client.get("/api/auth/status").json() == {"registration_enabled": True}
    registered = client.post(
        "/api/auth/register",
        json={"username": "owner", "password": "correct-horse", "device_name": "电脑"},
    )
    assert registered.status_code == 200
    first = registered.json()
    assert first["token"]
    assert client.get("/api/auth/status").json() == {"registration_enabled": True}

    wrong = client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "wrong-pass"},
    )
    assert wrong.status_code == 401

    logged_in = client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "correct-horse", "device_name": "手机"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["token"] != first["token"]


def test_register_is_only_allowed_once(client: TestClient) -> None:
    payload = {"username": "owner", "password": "correct-horse"}
    assert client.post("/api/auth/register", json=payload).status_code == 200
    again = client.post("/api/auth/register", json=payload)
    assert again.status_code == 409


def test_registration_can_be_disabled_after_initial_setup(client: TestClient) -> None:
    from app.core.config import get_settings

    payload = {"username": "owner", "password": "correct-horse"}
    assert client.post("/api/auth/register", json=payload).status_code == 200
    get_settings().allow_registration = False

    assert client.get("/api/auth/status").json() == {"registration_enabled": False}
    disabled = client.post("/api/auth/register", json=payload)
    assert disabled.status_code == 403
    assert disabled.json()["detail"]["code"] == "registration_disabled"


def test_login_failures_are_rate_limited(client: TestClient) -> None:
    login_failures.reset()
    assert (
        client.post(
            "/api/auth/register", json={"username": "owner", "password": "correct-horse"}
        ).status_code
        == 200
    )
    for _ in range(5):
        assert (
            client.post(
                "/api/auth/login", json={"username": "owner", "password": "wrong-pass"}
            ).status_code
            == 401
        )
    limited = client.post("/api/auth/login", json={"username": "owner", "password": "wrong-pass"})
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "900"
    login_failures.reset()
