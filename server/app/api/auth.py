"""账号密码登录；登录后仍复用现有设备令牌和同步协议。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import create_device_token
from app.core.config import get_settings
from app.core.db import get_session
from app.core.journal import now_iso
from app.core.rate_limit import login_failures
from app.models import Account

router = APIRouter(prefix="/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_session)]


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _credentials(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    name = str(payload.get("device_name", "浏览器")).strip() or "浏览器"
    platform = str(payload.get("platform", "web")).strip() or "web"
    if not 1 <= len(username) <= 64 or len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_credentials", "message": "账号不能为空，密码至少 8 位"},
        )
    return username, password, name[:64], platform[:32]


@router.get("/status")
def auth_status() -> dict[str, bool]:
    return {"registration_enabled": get_settings().allow_registration}


@router.post("/register")
def register(payload: dict[str, Any], session: Db) -> dict[str, Any]:
    if not get_settings().allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "registration_disabled", "message": "当前服务器已关闭注册"},
        )
    if session.execute(select(Account.id)).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "account_exists", "message": "账号已经创建，请直接登录"},
        )
    username, password, device_name, platform = _credentials(payload)
    account = Account(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password(password),
        created_at=now_iso(),
    )
    session.add(account)
    device_id, token = create_device_token(session, device_name, platform)
    return {"username": account.username, "device_id": device_id, "token": token}


@router.post("/login")
def login(request: Request, payload: dict[str, Any], session: Db) -> dict[str, Any]:
    username, password, device_name, platform = _credentials(payload)
    key = f"{request.client.host if request.client else 'unknown'}:{username.casefold()}"
    if not login_failures.allow(key, limit=5, window=15 * 60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "login_rate_limited", "message": "登录尝试过于频繁，请稍后再试"},
            headers={"Retry-After": "900"},
        )
    account = session.execute(
        select(Account).where(Account.username == username)
    ).scalar_one_or_none()
    if account is None or not verify_password(password, account.password_hash):
        login_failures.record(key, window=15 * 60)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_login", "message": "账号或密码错误"},
        )
    login_failures.clear(key)
    device_id, token = create_device_token(session, device_name, platform)
    return {"username": account.username, "device_id": device_id, "token": token}


__all__ = ["router", "hash_password", "verify_password"]
