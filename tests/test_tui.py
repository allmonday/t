from __future__ import annotations

import pytest

from todo_cli.tui import TodoApp, TodoTree


@pytest.fixture
async def store():
    """异步 TodoStore，使用 :memory: 数据库。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from todo_cli.models import Base
    from todo_cli.store import TodoStore

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    s = TodoStore(session_factory)
    yield s
    await engine.dispose()


def _cursor_todo_id(app: TodoApp) -> int | None:
    """获取当前光标选中的 todo id，root 节点返回 None。"""
    tree = app.query_one(TodoTree)
    node = tree.cursor_node
    if node and node.data is not None:
        return node.data
    return None


async def _type_and_submit(pilot, text: str):
    """在 InputScreen 中输入文本并提交。"""
    await pilot.press(*list(text))
    await pilot.press("enter")
    await pilot.pause()


# ── add_root ──


async def test_add_root_cursor_on_new_todo(store):
    await store.add("existing task")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await _type_and_submit(pilot, "new root")
        await pilot.pause()

        todo_id = _cursor_todo_id(app)
        assert todo_id is not None, "cursor should not be on root"
        todo = await store.get(todo_id)
        assert todo.text == "new root"
        assert todo.parent is None


# ── add_sibling ──


async def test_add_sibling_of_child(store):
    """child 的 sibling 应在同一 parent 下，光标选中新建项。"""
    root = await store.add("root")
    child = await store.add("child1", parent_id=root.id)
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("l")
        await pilot.press("j")
        assert _cursor_todo_id(app) == child.id

        await pilot.press("a")
        await _type_and_submit(pilot, "child2")
        await pilot.pause()

        todo_id = _cursor_todo_id(app)
        assert todo_id is not None, "cursor should not be on root"
        todo = await store.get(todo_id)
        assert todo.text == "child2"
        assert todo.parent == root.id


# ── add_child ──


async def test_add_child_under_root(store):
    root = await store.add("root")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        assert _cursor_todo_id(app) == root.id

        await pilot.press("tab")
        await _type_and_submit(pilot, "sub")
        await pilot.pause()

        todo_id = _cursor_todo_id(app)
        assert todo_id is not None, "cursor should not be on root"

        children = await store.get_children(root.id)
        assert len(children) == 1
        assert children[0].text == "sub"
        assert todo_id == children[0].id


async def test_add_child_consecutive_keeps_expanded(store):
    """连续 Tab 添加子节点，父节点应保持展开，光标停在新子节点上。"""
    root = await store.add("root")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        assert _cursor_todo_id(app) == root.id

        await pilot.press("tab")
        await _type_and_submit(pilot, "c1")
        await pilot.pause()

        children = await store.get_children(root.id)
        assert len(children) == 1
        assert _cursor_todo_id(app) == children[0].id

        # 回到 root 再添加第二个子节点
        await pilot.press("k")
        assert _cursor_todo_id(app) == root.id

        await pilot.press("tab")
        await _type_and_submit(pilot, "c2")
        await pilot.pause()

        children = await store.get_children(root.id)
        assert len(children) == 2
        assert _cursor_todo_id(app) == children[1].id


# ── delete ──


async def test_delete_only_todo_cursor_at_root(store):
    """删除唯一的 todo 后，光标回到 root。"""
    await store.add("only task")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("d")
        await pilot.press("y")
        await pilot.pause()
        assert _cursor_todo_id(app) is None


async def test_delete_child_cursor_not_at_root(store):
    """删除一个 child 后，树还在，光标不在 root。"""
    root = await store.add("root")
    await store.add("c1", parent_id=root.id)
    c2 = await store.add("c2", parent_id=root.id)
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("l")
        await pilot.press("j")
        await pilot.press("j")
        assert _cursor_todo_id(app) == c2.id

        await pilot.press("d")
        await pilot.press("y")
        await pilot.pause()

        assert _cursor_todo_id(app) is not None, "cursor should not be on root after delete"


# ── toggle ──


async def test_toggle_preserves_cursor(store):
    root = await store.add("root")
    child = await store.add("child", parent_id=root.id)
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("l")
        await pilot.press("j")
        assert _cursor_todo_id(app) == child.id

        await pilot.press("space")
        await pilot.pause()

        assert _cursor_todo_id(app) == child.id
        assert (await store.get(child.id)).done is True
