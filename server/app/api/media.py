"""图片媒体：鉴权上传、内容校验、EXIF 方向修正、哈希去重与缓存读取。"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import CurrentDeviceId
from app.core.config import get_settings
from app.core.db import get_session
from app.core.journal import next_rev, now_iso
from app.models import Media

router = APIRouter(tags=["media"])
Db = Annotated[Session, Depends(get_session)]

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MIME_TO_FORMAT = {
    "image/jpeg": ("jpg", "JPEG"),
    "image/png": ("png", "PNG"),
    "image/webp": ("webp", "WEBP"),
    "image/gif": ("gif", "GIF"),
}


def _bad(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "message": message},
    )


@router.post("/media")
async def upload_media(
    device_id: CurrentDeviceId,
    session: Db,
    id: Annotated[str, Form()],
    sha256: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """上传一张图片；文件本体不进入同步日志，元数据进入 media 表。"""
    if not _ID_RE.fullmatch(id):
        raise _bad("invalid_id", "媒体 ID 格式无效")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise _bad("invalid_sha256", "sha256 格式无效")
    if file.content_type not in _MIME_TO_FORMAT:
        raise _bad("unsupported_type", "仅支持 JPEG、PNG、WebP、GIF 图片")

    settings = get_settings()
    raw = await file.read(settings.media_max_bytes + 1)
    if len(raw) > settings.media_max_bytes:
        raise _bad("file_too_large", "图片超过 6MB 限制")
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise _bad("sha256_mismatch", "文件校验失败")

    try:
        with Image.open(BytesIO(raw)) as source:
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            expected_format = _MIME_TO_FORMAT[file.content_type][1]
            if source.format != expected_format:
                raise _bad("content_type_mismatch", "图片类型与文件内容不一致")
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            ext, image_format = _MIME_TO_FORMAT[file.content_type]
            if image_format == "JPEG" and image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = BytesIO()
            save_kwargs = (
                {"quality": 90, "optimize": True} if image_format in ("JPEG", "WEBP") else {}
            )
            image.save(output, format=image_format, **save_kwargs)
            normalized = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise _bad("invalid_image", "图片内容无法读取") from exc

    existing = session.execute(select(Media).where(Media.sha256 == sha256)).scalar_one_or_none()
    if existing is not None:
        existing_path = _media_path(existing.id, existing.ext)
        if not existing_path.is_file():
            existing_path.write_bytes(normalized)
        return _media_result(existing, deduped=True)

    media = Media(
        id=id,
        rev=next_rev(session),
        updated_at=now_iso(),
        deleted_at=None,
        sha256=sha256,
        mime=file.content_type,
        ext=ext,
        bytes=len(normalized),
        width=width,
        height=height,
        filename=(file.filename or "图片")[:255],
        uploaded=1,
        created_at=now_iso(),
    )
    session.add(media)
    session.flush()
    _media_path(media.id, media.ext).write_bytes(normalized)
    return _media_result(media, deduped=False)


@router.get("/media/{media_id}")
def get_media(
    media_id: str,
    request: Request,
    device_id: CurrentDeviceId,
    session: Db,
) -> Response:
    media = session.get(Media, media_id)
    if media is None or media.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "图片不存在"},
        )
    path = _media_path(media.id, media.ext)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "file_missing", "message": "图片文件不存在"},
        )
    etag = f'"{media.sha256}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return FileResponse(
        path,
        media_type=media.mime,
        headers={"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"},
    )


def _media_path(media_id: str, ext: str) -> Path:
    path = get_settings().media_dir / f"{media_id}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _media_result(media: Media, *, deduped: bool) -> dict[str, Any]:
    return {
        "id": media.id,
        "url": f"/api/media/{media.id}",
        "bytes": media.bytes,
        "width": media.width,
        "height": media.height,
        "deduped": deduped,
    }


__all__ = ["router"]
