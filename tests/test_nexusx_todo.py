"""Tests for nexusx src/ todo & pomodoro methods."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from sqlmodel import SQLModel, select

from src.db import async_session, engine
from src.models import Audit, PomodoroSession, Todo
from src.service.pomodoro.methods import record_session, today_sessions
from src.service.todo.methods import (
    add_todo,
    delete_todo,
    get_audit,
    get_children,
    get_descendants,
    get_todo,
    has_children,
    list_todos,
    toggle_pin,
    toggle_todo,
    update_desc,
    update_text,
)


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch):
    """Create in-memory DB and patch async_session for all methods modules."""
    test_engine = engine
    test_factory = async_session

    async def setup():
        async with test_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)

    asyncio.get_event_loop().run_until_complete(setup())

    # Patch every module that imported async_session from src.db
    import src.service.todo.methods as todo_mod
    import src.service.pomodoro.methods as pomo_mod

    monkeypatch.setattr("src.db.async_session", test_factory)
    monkeypatch.setattr(todo_mod, "async_session", test_factory)
    monkeypatch.setattr(pomo_mod, "async_session", test_factory)


# ── todo ──


@pytest.mark.asyncio
async def test_add_root():
    todo = await add_todo("root task")
    assert todo.text == "root task"
    assert todo.parent_id is None
    assert todo.done is False


@pytest.mark.asyncio
async def test_add_child():
    parent = await add_todo("parent")
    child = await add_todo("child", parent_id=parent.id)
    assert child.parent_id == parent.id


@pytest.mark.asyncio
async def test_get_todo():
    created = await add_todo("find me")
    found = await get_todo(created.id)
    assert found is not None
    assert found.text == "find me"


@pytest.mark.asyncio
async def test_get_todo_not_found():
    assert await get_todo(9999) is None


@pytest.mark.asyncio
async def test_list_todos():
    await add_todo("a")
    await add_todo("b")
    todos = await list_todos()
    assert len(todos) == 2


@pytest.mark.asyncio
async def test_list_todos_filter_done():
    await add_todo("pending")
    t = await add_todo("done")
    await toggle_todo(t.id)
    done = await list_todos(filter_done=True)
    assert len(done) == 1
    assert done[0].text == "done"


@pytest.mark.asyncio
async def test_get_children():
    parent = await add_todo("p")
    await add_todo("c1", parent_id=parent.id)
    await add_todo("c2", parent_id=parent.id)
    children = await get_children(parent.id)
    assert len(children) == 2


@pytest.mark.asyncio
async def test_has_children():
    parent = await add_todo("p")
    assert await has_children(parent.id) is False
    await add_todo("c", parent_id=parent.id)
    assert await has_children(parent.id) is True


@pytest.mark.asyncio
async def test_get_descendants():
    root = await add_todo("root")
    c1 = await add_todo("c1", parent_id=root.id)
    await add_todo("c1a", parent_id=c1.id)
    descs = await get_descendants(root.id)
    assert len(descs) == 2


@pytest.mark.asyncio
async def test_toggle_todo_leaf():
    t = await add_todo("leaf")
    assert await toggle_todo(t.id) is True
    found = await get_todo(t.id)
    assert found.done is True


@pytest.mark.asyncio
async def test_toggle_todo_parent_fails():
    parent = await add_todo("p")
    await add_todo("c", parent_id=parent.id)
    assert await toggle_todo(parent.id) is False


@pytest.mark.asyncio
async def test_toggle_pin_root():
    t = await add_todo("root")
    assert await toggle_pin(t.id) is True
    found = await get_todo(t.id)
    assert found.pinned is True


@pytest.mark.asyncio
async def test_toggle_pin_child_fails():
    parent = await add_todo("p")
    child = await add_todo("c", parent_id=parent.id)
    with pytest.raises(ValueError):
        await toggle_pin(child.id)


@pytest.mark.asyncio
async def test_delete_todo():
    parent = await add_todo("p")
    child = await add_todo("c", parent_id=parent.id)
    count = await delete_todo(parent.id)
    assert count == 2
    assert await get_todo(parent.id) is None
    assert await get_todo(child.id) is None


@pytest.mark.asyncio
async def test_update_text():
    t = await add_todo("old")
    assert await update_text(t.id, "new") is True
    found = await get_todo(t.id)
    assert found.text == "new"


@pytest.mark.asyncio
async def test_update_desc():
    t = await add_todo("t")
    assert await update_desc(t.id, "my desc") is True
    found = await get_todo(t.id)
    assert found.desc == "my desc"


@pytest.mark.asyncio
async def test_get_audit():
    await add_todo("audited")
    audits = await get_audit(limit=10)
    assert len(audits) >= 1
    assert audits[0].action == "add"


# ── pomodoro ──


@pytest.mark.asyncio
async def test_record_session():
    now = datetime.now().isoformat()
    s = await record_session(
        started_at=now, finished_at=now,
        phase="focus", duration_seconds=1500, completed=True,
    )
    assert s.phase == "focus"
    assert s.completed is True


@pytest.mark.asyncio
async def test_today_sessions():
    now = datetime.now().isoformat()
    await record_session(
        started_at=now, finished_at=now,
        phase="focus", duration_seconds=1500, completed=True,
    )
    sessions = await today_sessions()
    assert len(sessions) >= 1
