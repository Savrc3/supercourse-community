"""媒体上传接口回归测试。"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _png() -> bytes:
    image = Image.new("RGB", (3, 2), (31, 111, 235))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_upload_get_dedupe_and_etag(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    content = _png()
    digest = hashlib.sha256(content).hexdigest()
    payload = {"id": "media-1", "sha256": digest}
    files = {"file": ("demo.png", content, "image/png")}

    uploaded = client.post("/api/media", data=payload, files=files, headers=_auth(token))
    assert uploaded.status_code == 200
    assert uploaded.json() == {
        "id": "media-1",
        "url": "/api/media/media-1",
        "bytes": uploaded.json()["bytes"],
        "width": 3,
        "height": 2,
        "deduped": False,
    }

    response = client.get("/api/media/media-1", headers=_auth(token))
    assert response.status_code == 200
    assert response.content == content
    etag = response.headers["etag"]
    cached = client.get("/api/media/media-1", headers={**_auth(token), "If-None-Match": etag})
    assert cached.status_code == 304

    duplicate = client.post(
        "/api/media",
        data={"id": "media-2", "sha256": digest},
        files={"file": ("copy.png", content, "image/png")},
        headers=_auth(token),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["deduped"] is True
    assert duplicate.json()["id"] == "media-1"


def test_upload_rejects_invalid_type_and_hash(authed_client: tuple[TestClient, str, str]) -> None:
    client, token, _ = authed_client
    content = b"not an image"
    headers = _auth(token)
    rejected_type = client.post(
        "/api/media",
        data={"id": "media-1", "sha256": hashlib.sha256(content).hexdigest()},
        files={"file": ("note.txt", content, "text/plain")},
        headers=headers,
    )
    assert rejected_type.status_code == 400
    assert rejected_type.json()["detail"]["code"] == "unsupported_type"

    rejected_hash = client.post(
        "/api/media",
        data={"id": "media-1", "sha256": "0" * 64},
        files={"file": ("note.png", _png(), "image/png")},
        headers=headers,
    )
    assert rejected_hash.status_code == 400
    assert rejected_hash.json()["detail"]["code"] == "sha256_mismatch"

    mismatch = client.post(
        "/api/media",
        data={"id": "media-2", "sha256": hashlib.sha256(_png()).hexdigest()},
        files={"file": ("note.jpg", _png(), "image/jpeg")},
        headers=headers,
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["detail"]["code"] == "content_type_mismatch"


def test_push_rejects_media_path_traversal(authed_client: tuple[TestClient, str, str]) -> None:
    """同步 op 不能把任意 ext 写进 media 行（否则读接口就是任意文件读取）。"""
    client, token, _ = authed_client
    resp = client.post(
        "/api/sync/push",
        json={
            "ops": [
                {
                    "op_id": "op-media-evil",
                    "entity": "media",
                    "id": "evil",
                    "set": {
                        "sha256": "0" * 64,
                        "mime": "image/png",
                        "ext": "../../../app.db",
                        "bytes": 1,
                        "uploaded": 1,
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    "base_rev": 0,
                }
            ]
        },
        headers=_auth(token),
    )
    result = resp.json()["results"][0]
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "invalid_media_ext"


def test_media_read_rejects_dirty_row(authed_client: tuple[TestClient, str, str]) -> None:
    """库里已有越界 ext 的脏行（历史数据/直接写库）也读不到 media 目录外的文件。"""
    from sqlalchemy.orm import Session

    from app.core.config import get_settings
    from app.core.db import make_engine
    from app.models import Media

    client, token, _ = authed_client
    settings = get_settings()
    secret = settings.data_dir / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    with Session(make_engine()) as session:
        session.add(
            Media(
                id="evil",
                rev=1,
                updated_at="2026-01-01T00:00:00+00:00",
                deleted_at=None,
                sha256="0" * 64,
                mime="image/png",
                ext="../../../secret.txt",
                bytes=10,
                width=None,
                height=None,
                filename=None,
                uploaded=1,
                created_at="2026-01-01T00:00:00+00:00",
            )
        )
        session.commit()

    resp = client.get("/api/media/evil", headers=_auth(token))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_media_path"
    assert b"TOP-SECRET" not in resp.content


def test_media_file_path_rejects_traversal(tmp_path: Path) -> None:
    from app.core.media_rules import media_file_path

    assert media_file_path(tmp_path, "ok", "png") == tmp_path.resolve() / "ok.png"
    assert media_file_path(tmp_path, "evil", "../../app.db") is None
    assert media_file_path(tmp_path, "../evil", "png") is None
    assert media_file_path(tmp_path, "evil", "png/../../app.db") is None
    assert media_file_path(tmp_path, "", "png") is None
