"""运维 CLI：设备签发、配对、备份恢复。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.auth import create_device_token
from app.core.auth import create_pairing as _auth_create_pairing
from app.core.db import make_engine, session_scope
from app.sync.backup import export_all, restore_all

app = typer.Typer(help="课序运维命令")


def _ensure_schema(engine: Engine) -> None:
    """首次空库时自动跑迁移，保证 CLI 在直连空库也能用。"""
    from alembic import command
    from alembic.config import Config

    if "seq" in inspect(engine).get_table_names():
        return
    here = Path(__file__).resolve().parent.parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "alembic"))
    command.upgrade(cfg, "head")


@contextmanager
def _cli_session() -> Iterator[Session]:
    engine = make_engine()
    _ensure_schema(engine)
    with session_scope(engine) as session:
        yield session


@app.command()
def issue_device(
    name: Annotated[str, typer.Option("--name", help="设备名")] = "PC",
    platform: Annotated[str, typer.Option("--platform", help="平台")] = "web",
) -> None:
    """签发首个设备令牌（一次性打印明文，库里只存 SHA-256）。"""
    with _cli_session() as session:
        device_id, credential = create_device_token(session, name, platform)
        typer.echo(f"device_id: {device_id}")
        typer.echo(f"token:     {credential}")
        typer.echo("(令牌仅显示这一次，请妥善保管)")


@app.command()
def make_pairing_code(
    name: Annotated[str, typer.Option("--name", help="请求设备名")] = "PC",
    platform: Annotated[str, typer.Option("--platform", help="平台")] = "web",
) -> None:
    """生成一次配对码（5 分钟过期）。"""
    with _cli_session() as session:
        device_id, _ = create_device_token(session, name, platform)
    with _cli_session() as session:
        code, ttl = _auth_create_pairing(session, device_id)
        typer.echo(f"code:       {code}")
        typer.echo(f"expires_in: {ttl}s")


@app.command()
def export(
    path: Annotated[Path, typer.Argument(help="输出 JSON 文件路径")] = Path("export.json"),
) -> None:
    """全量导出。"""
    with _cli_session() as session:
        data = export_all(session)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        typer.echo(f"已导出 {path}（{len(data['rows'])} 类）")


@app.command()
def restore(
    path: Annotated[Path, typer.Argument(help="输入 JSON 文件路径")] = Path("export.json"),
) -> None:
    """从导出文件恢复（保留原 id）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    with _cli_session() as session:
        result = restore_all(session, data)
        typer.echo(f"已恢复 {result['restored']} 行")


@app.command()
def backup(
    path: Annotated[Path, typer.Argument(help="输出备份文件路径")] = Path("backup.json"),
) -> None:
    """备份 = export 的别名，便于 cron 调用。"""
    with _cli_session() as session:
        data = export_all(session)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        typer.echo(f"备份完成 {path}")


@app.command()
def seed_demo() -> None:
    """注入默认作息表 + 一个示例学期（幂等）。"""
    from app.seed import seed_demo as _do_seed

    with _cli_session() as session:
        term_id = _do_seed(session)
        typer.echo(f"已注入演示数据，term_id={term_id}, 作息表 11 小节")


if __name__ == "__main__":
    app()
