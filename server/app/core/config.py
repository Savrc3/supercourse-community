"""运行期配置：环境变量（前缀 SC_）优先，其次 .env，最后默认值。

敏感值（设备令牌、QQ 号）只从环境变量读取，永不写进仓库。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项。"""

    model_config = SettingsConfigDict(env_prefix="SC_", env_file=".env", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    data_dir: Path = Field(default=Path("./data"), description="SQLite 与图片根目录")
    log_level: str = "INFO"
    host: str = "localhost"
    port: int = 8090
    tombstone_days: int = 60
    media_max_bytes: int = 6 * 1024 * 1024
    android_update_url: str | None = None
    pairing_code_ttl: int = 300
    max_request_bytes: int = 20 * 1024 * 1024
    allow_registration: bool = True
    expose_health_details: bool = True
    allowed_origins: str = ""
    qq_enabled: bool = False
    onebot_url: str = "http://localhost:3000"
    onebot_token: str = ""
    qq_target_user_id: int = 0

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def ensure_dirs(self) -> None:
        self.media_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
