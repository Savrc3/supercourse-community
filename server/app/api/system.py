"""系统级端点：探活与版本，无需鉴权。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.version import APP_VERSION
from app.modules.remind.engine import scheduler_ok

router = APIRouter(tags=["system"])


def _dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    if not settings.expose_health_details:
        return {"ok": True, "version": APP_VERSION}
    db = settings.db_path
    return {
        "ok": True,
        "version": APP_VERSION,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_bytes": db.stat().st_size if db.exists() else 0,
        "media_bytes": _dir_bytes(settings.media_dir),
        "scheduler_ok": scheduler_ok(),
    }


@router.get("/version")
def version() -> dict[str, Any]:
    settings = get_settings()
    return {
        "api": APP_VERSION,
        "web": APP_VERSION,
        "android": APP_VERSION,
        "android_url": settings.android_update_url,
        "desktop": None,
    }
