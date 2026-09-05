"""NapCat OneBot 私聊通道。"""

from __future__ import annotations

import httpx

from app.core.config import Settings


def send_private_message(settings: Settings, message: str) -> None:
    """向配置的 QQ 账号发送纯文本消息。"""
    if not settings.qq_enabled or settings.qq_target_user_id <= 0:
        raise RuntimeError("QQ 提醒未配置")
    response = httpx.post(
        f"{settings.onebot_url.rstrip('/')}/send_private_msg",
        json={"user_id": settings.qq_target_user_id, "message": message[:500]},
        headers={"Authorization": f"Bearer {settings.onebot_token}"}
        if settings.onebot_token
        else None,
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "failed" or payload.get("retcode", 0) != 0:
        raise RuntimeError(
            str(payload.get("message") or payload.get("wording") or "QQ 通道返回失败")
        )
