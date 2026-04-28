from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from todo_cli.models import TodoEntity

# 相对于当前时间，避免跨年问题
_NOW = datetime.now()
TODAY_ISO = _NOW.isoformat()
YESTERDAY_ISO = (_NOW - timedelta(days=1)).isoformat()
THREE_DAYS_AGO_ISO = (_NOW - timedelta(days=3)).isoformat()
TEN_DAYS_AGO_ISO = (_NOW - timedelta(days=10)).isoformat()


def _make_todo(
    id: int,
    text: str,
    done: bool = False,
    parent: int | None = None,
    created: str = TODAY_ISO,
    done_at: str | None = None,
    deleted_at: str | None = None,
    desc: str | None = None,
) -> TodoEntity:
    return TodoEntity(id=id, text=text, desc=desc, done=done, parent=parent,
                      created=created, done_at=done_at, deleted_at=deleted_at)


# ── tree.py fixtures ──


@pytest.fixture
def sample_todos() -> list[TodoEntity]:
    """
    #1 根A (undone)
      #4 A1 (undone)
      #5 A2 (done, done_at=today)
    #2 根B (done, done_at=today)
      #6 B1 (done)
      #7 B2 (done)
    #3 根C (undone)
      #8 C1 (undone)
        #9 C1a (undone)
    """
    return [
        _make_todo(1, "根A", False, None),
        _make_todo(2, "根B", True, None, done_at=TODAY_ISO),
        _make_todo(3, "根C", False, None),
        _make_todo(4, "A1", False, 1),
        _make_todo(5, "A2", True, 1, done_at=TODAY_ISO),
        _make_todo(6, "B1", True, 2, done_at=TODAY_ISO),
        _make_todo(7, "B2", True, 2, done_at=TODAY_ISO),
        _make_todo(8, "C1", False, 3),
        _make_todo(9, "C1a", False, 8),
    ]


@pytest.fixture
def stale_todos() -> list[TodoEntity]:
    """含过期完成根节点，用于 stale 过滤测试。done_at 基于 datetime.now() 动态计算。"""
    return [
        _make_todo(1, "新鲜完成", True, None, done_at=YESTERDAY_ISO),
        _make_todo(2, "过期完成", True, None, done_at=TEN_DAYS_AGO_ISO),
        _make_todo(3, "未完成根", False, None),
        _make_todo(4, "过期子任务", True, 2, done_at=TEN_DAYS_AGO_ISO),
    ]


@pytest.fixture
def empty_todos() -> list[TodoEntity]:
    return []


@pytest.fixture
def single_todo() -> list[TodoEntity]:
    return [_make_todo(1, "唯一任务", False, None)]


# ── store.py fixtures ──


@pytest.fixture
async def store():
    """已连接、使用 :memory: 的 TodoStore，清空种子数据。"""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    from todo_cli.models import Base
    from todo_cli.store import TodoStore

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    s = TodoStore(session_factory)
    yield s
    await engine.dispose()
