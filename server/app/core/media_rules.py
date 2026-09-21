"""媒体文件名的唯一校验入口：id/ext 白名单 + 落盘路径必须留在 media 目录内。

媒体行的 ``id``/``ext`` 会被拼成 ``media_dir/{id}.{ext}``。它们来自
同步 op（``POST /sync/push``）与备份恢复（``POST /restore``），因此可能是
任意客户端字符串——不校验就等于把服务器文件系统暴露给已配对的设备。
上传接口与读取接口都必须走这里的规则。
"""

from __future__ import annotations

import re
from pathlib import Path

# 客户端生成的媒体 id 形如 UUID / 简写短 id。
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
ALLOWED_MIMES: frozenset[str] = frozenset(MIME_TO_EXT)
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(MIME_TO_EXT.values())


def is_valid_media_id(value: object) -> bool:
    """媒体 id 是否为安全文件名片段（无路径分隔符、无点号开头）。"""
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def is_valid_media_ext(value: object) -> bool:
    """扩展名是否属于图片白名单。"""
    return isinstance(value, str) and value in ALLOWED_EXTENSIONS


def media_file_path(media_dir: Path, media_id: object, ext: object) -> Path | None:
    """返回 media 目录内的真实文件路径；id/ext 非法或越界时返回 None。

    双重保险：既做白名单，也把 resolve 后的路径与 media 根目录比对，
    防止 ``..``、绝对路径、符号链接等绕过。
    """
    if not is_valid_media_id(media_id) or not is_valid_media_ext(ext):
        return None
    root = media_dir.resolve()
    path = (root / f"{media_id}.{ext}").resolve()
    if path.parent != root:
        return None
    return path


def path_is_inside(root: Path, path: Path) -> bool:
    """path 是否落在 root 目录内（供调用方做额外断言）。"""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


__all__ = [
    "ALLOWED_EXTENSIONS",
    "ALLOWED_MIMES",
    "ID_RE",
    "MIME_TO_EXT",
    "is_valid_media_ext",
    "is_valid_media_id",
    "media_file_path",
    "path_is_inside",
]
