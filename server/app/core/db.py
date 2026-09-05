"""数据库底座：Engine、Session、声明式 Base。

SQLite 三个 pragma 缺一不可：WAL（读写不互斥）、foreign_keys（默认关闭）、
busy_timeout（多端偶发并发写时等 5 秒而不是直接报错）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_SessionMaker: sessionmaker[Session] | None = None
_SessionMakerUrl: str | None = None


class Base(DeclarativeBase):
    """全部 ORM 模型的基类，Alembic 靠它的 metadata 生成迁移。"""


def make_engine(url: str | None = None) -> Engine:
    engine = create_engine(
        url or get_settings().database_url,
        future=True,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """事务边界：正常提交，异常回滚。"""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_engine() -> Engine:
    """按当前 data_dir 返回进程级共享 Engine（Lazy 初始化）。"""
    global _SessionMaker
    _ensure_sessionmaker()
    assert _SessionMaker is not None
    return _SessionMaker.kw["bind"]  # type: ignore[no-any-return]


def _ensure_sessionmaker() -> None:
    """按当前 settings.database_url 缓存 sessionmaker；换了 data_dir 就重建。"""
    global _SessionMaker, _SessionMakerUrl
    url = get_settings().database_url
    if _SessionMaker is not None and _SessionMakerUrl == url:
        return
    if _SessionMakerUrl != url:
        _SessionMaker = make_sessionmaker(make_engine())
        _SessionMakerUrl = url


def get_session() -> Iterator[Session]:
    """FastAPI 请求级 session 依赖：正常提交，异常回滚。"""
    _ensure_sessionmaker()
    assert _SessionMaker is not None
    session = _SessionMaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
