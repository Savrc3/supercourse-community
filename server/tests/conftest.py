"""测试夹具：每个用例独立的临时数据目录与 TestClient。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _run_migrations(data_dir: Path) -> None:
    """用 Alembic API 把库升到 head（表结构 = 定稿 DDL）。"""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "alembic"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    data_dir = tmp_path / "data"
    (data_dir / "media").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SC_ENV", "dev")
    from app.core.config import get_settings

    get_settings.cache_clear()
    # 跑迁移保证表结构 = 定稿 DDL。
    _run_migrations(data_dir)
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """独立 session，供需要直接操作库的测试使用。"""
    data_dir = tmp_path / "data"
    (data_dir / "media").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SC_ENV", "dev")
    from app.core.config import get_settings

    get_settings.cache_clear()
    _run_migrations(data_dir)
    from app.core.db import make_engine

    engine = make_engine()
    with Session(engine) as session:
        yield session
    get_settings.cache_clear()


@pytest.fixture()
def authed_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, str]]:
    """已鉴权客户端 + token + device_id（同一临时库）。"""
    data_dir = tmp_path / "data"
    (data_dir / "media").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SC_ENV", "dev")
    from app.core.auth import create_device_token
    from app.core.config import get_settings
    from app.core.db import make_engine

    get_settings.cache_clear()
    _run_migrations(data_dir)
    engine = make_engine()
    with Session(engine) as session:
        device_id, token = create_device_token(session, "pc-test", "web")
        session.commit()

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client, token, device_id
    get_settings.cache_clear()
