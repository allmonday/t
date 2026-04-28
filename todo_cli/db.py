from __future__ import annotations

import asyncio
import os
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DEFAULT_DB_PATH = os.environ.get("TODO_DB", "~/.todo.db")


def create_engine_and_session(db_path: str | None = None):
    """创建 async engine 和 session_factory。"""
    if db_path is None:
        db_path = os.path.expanduser(DEFAULT_DB_PATH)
    else:
        db_path = os.path.expanduser(db_path)

    if db_path == ":memory:":
        url = "sqlite+aiosqlite://"
    else:
        url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def init_db(engine) -> None:
    """PRAGMA 设置 + 通过 alembic migration 建表/迁移。"""
    from alembic.config import Config as AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from .models import Base

    alembic_dir = os.path.join(os.path.dirname(__file__), "alembic")
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", alembic_dir)
    script = ScriptDirectory.from_config(cfg)

    def _stamp_legacy_db(connection):
        """旧数据库（create_all 创建）没有 alembic_version，需先 stamp。"""
        result = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
        )
        if result.fetchone() is None:
            result = connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='todos'")
            )
            if result.fetchone() is not None:
                init_rev = script.get_bases()[0]
                stamp_ctx = MigrationContext.configure(connection)
                stamp_ctx._ensure_version_table()
                connection.execute(
                    stamp_ctx._version.insert().values(version_num=init_rev)
                )

    def _run_migrations(connection):
        from alembic.operations import Operations

        def upgrade(rev, _context):
            return script._upgrade_revs("head", rev)

        ctx = MigrationContext.configure(
            connection,
            opts={
                "target_metadata": Base.metadata,
                "fn": upgrade,
                "render_as_batch": True,
            },
        )
        with Operations.context(ctx):
            with ctx.begin_transaction():
                ctx.run_migrations()

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.run_sync(_stamp_legacy_db)
        await conn.run_sync(_run_migrations)


async def seed_if_empty(session_factory: async_sessionmaker) -> None:
    """首次运行时插入种子数据。"""
    from .models import TodoORM

    from sqlalchemy import func, select

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(TodoORM))
        if count and count > 0:
            return
        now = datetime.now().isoformat()
        seeds_root = [
            ("快速上手 Todo CLI", False),
            ("示例项目", False),
            ("按 d 删除此任务试试", False),
        ]
        root_ids: list[int] = []
        for text, done in seeds_root:
            orm = TodoORM(text=text, done=int(done), parent=None, created=now)
            session.add(orm)
            await session.flush()
            root_ids.append(orm.id)

        seed_children = [
            ("按 Space 切换完成状态", False, root_ids[0]),
            ("按 Tab 添加子任务", False, root_ids[0]),
            ("按 ←→ 折叠/展开树节点", False, root_ids[0]),
            ("设计方案", True, root_ids[1]),
            ("编码实现", False, root_ids[1]),
        ]
        for text, done, parent_id in seed_children:
            orm = TodoORM(
                text=text,
                done=int(done),
                parent=parent_id,
                created=now,
                done_at=now if done else None,
            )
            session.add(orm)
        await session.commit()
