"""鉴权：Bearer token → SHA-256 比对，注入 device_id；配对码一次一用。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.journal import now_iso
from app.models import Device, Pairing


class TokenHasher:
    """token 只存 SHA-256 散列，永不落明文。"""

    @staticmethod
    def hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


bearer = HTTPBearer(auto_error=False)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_device_token(session: Session, name: str, platform: str) -> tuple[str, str]:
    """签发明文 token + device_id。库里只存 token_hash。"""
    credential = secrets.token_urlsafe(32)
    device_id = f"dev-{secrets.token_hex(8)}"
    session.add(
        Device(
            id=device_id,
            name=name,
            platform=platform,
            token_hash=TokenHasher.hash(credential),
            created_at=now_iso(),
            last_seen_at=now_iso(),
        )
    )
    session.flush()
    return device_id, credential


def create_pairing(session: Session, created_by: str) -> tuple[str, int]:
    """生成一次性配对码 + 有效期（默认 300s）。返回 (明文码, ttl)。"""
    ttl = 300
    code = f"{secrets.randbelow(900) + 100}-{secrets.randbelow(900) + 100}-{secrets.randbelow(100)}"
    expires = (_utcnow() + timedelta(seconds=ttl)).isoformat(timespec="seconds")
    session.add(
        Pairing(
            code_hash=TokenHasher.hash(code),
            created_by=created_by,
            expires_at=expires,
        )
    )
    session.flush()
    return code, ttl


def exchange_pairing(
    session: Session,
    *,
    code: str,
    name: str,
    platform: str,
) -> tuple[str, str]:
    """用一次性码换长效令牌。过期 / 已用 / 无效一律拒绝。

    返回 (device_id, token)。仅此一次明文返回 token。
    """
    code_hash = TokenHasher.hash(code)
    pairing = session.get(Pairing, code_hash)
    if pairing is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_pairing", "message": "无效的配对码"},
        )
    if pairing.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_used", "message": "配对码已使用"},
        )
    if pairing.expires_at is None or pairing.expires_at < now_iso():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "pairing_expired", "message": "配对码已过期"},
        )
    pairing.used_at = now_iso()
    device_id, credential = create_device_token(session, name, platform)
    session.flush()
    return device_id, credential


def get_current_device_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
    session: Session = Depends(get_session),
) -> str:
    """Bearer 依赖：校验 token 散列匹配且未吊销，返回 device_id。"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_token", "message": "缺少 Bearer token"},
        )
    return authenticate_token(credentials.credentials, session)


def authenticate_token(raw_token: str, session: Session) -> str:
    """校验一个明文 token，供 Bearer API 和 SSE 等非标准客户端复用。"""
    token_hash = TokenHasher.hash(raw_token)
    device = session.execute(
        select(Device).where(Device.token_hash == token_hash)
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "无效的 token"},
        )
    if device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "device_revoked", "message": "设备已吊销"},
        )
    device.last_seen_at = now_iso()
    return device.id


CurrentDeviceId = Annotated[str, Depends(get_current_device_id)]


__all__ = [
    "TokenHasher",
    "bearer",
    "create_device_token",
    "create_pairing",
    "exchange_pairing",
    "get_current_device_id",
    "authenticate_token",
    "CurrentDeviceId",
]
