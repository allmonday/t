from __future__ import annotations

import pytest

from rich.text import Text

from todo_cli.models import TodoEntity
from todo_cli.tui import TodoApp, TodoTree, _render_label


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
        await pilot.press("o")
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

        await pilot.press("o")
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

        await pilot.press("O")
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

        await pilot.press("O")
        await _type_and_submit(pilot, "c1")
        await pilot.pause()

        children = await store.get_children(root.id)
        assert len(children) == 1
        assert _cursor_todo_id(app) == children[0].id

        # 回到 root 再添加第二个子节点
        await pilot.press("k")
        assert _cursor_todo_id(app) == root.id

        await pilot.press("O")
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


# ── _render_label ──


def _make_todo(
    id: int = 1,
    text: str = "task",
    done: bool = False,
    pinned: bool = False,
    parent: int | None = None,
    desc: str | None = None,
    created: str = "2026-01-01T00:00:00",
    done_at: str | None = None,
) -> TodoEntity:
    return TodoEntity(
        id=id, text=text, desc=desc, done=done, pinned=pinned,
        parent=parent, created=created, done_at=done_at,
    )


class TestRenderLabel:
    def test_basic_undone(self):
        todo = _make_todo()
        label = _render_label(todo)
        assert "task" in label.plain
        assert "#1" in label.plain

    def test_done_shows_strike(self):
        todo = _make_todo(done=True)
        label = _render_label(todo)
        assert "task" in label.plain
        # done 应包含 strike style
        styles = [s.style for s in label.spans]
        assert any("strike" in str(s) for s in styles)

    def test_undone_no_strike(self):
        todo = _make_todo(done=False)
        label = _render_label(todo)
        styles = [s.style for s in label.spans]
        assert not any("strike" in str(s) for s in styles)

    def test_pinned_shows_star(self):
        todo = _make_todo(pinned=True)
        label = _render_label(todo)
        assert "★" in label.plain

    def test_not_pinned_no_star(self):
        todo = _make_todo(pinned=False)
        label = _render_label(todo)
        assert "★" not in label.plain

    def test_desc_shows_info_icon(self):
        todo = _make_todo(desc="some description")
        label = _render_label(todo)
        assert "\u2139" in label.plain

    def test_no_desc_no_info_icon(self):
        todo = _make_todo()
        label = _render_label(todo)
        assert "\u2139" not in label.plain

    def test_desc_count(self):
        todo = _make_todo()
        label = _render_label(todo, desc_count=(2, 5))
        assert "[2/5]" in label.plain

    def test_no_desc_count(self):
        todo = _make_todo()
        label = _render_label(todo)
        assert "[" not in label.plain

    def test_done_time_shown_when_done(self):
        todo = _make_todo(done=True, done_at="2026-01-01T10:00:00")
        label = _render_label(todo)
        # done_at should produce a time string (exact format depends on format_time)
        plain = label.plain
        # the done_time is rendered after the todo content
        assert len(plain) > len("task #1")

    def test_done_pinned_with_desc_and_count(self):
        """组合场景：done + pinned + desc + desc_count。"""
        todo = _make_todo(done=True, pinned=True, desc="details")
        label = _render_label(todo, desc_count=(1, 3))
        plain = label.plain
        assert "★" in plain
        assert "task" in plain
        assert "\u2139" in plain
        assert "[1/3]" in plain

    def test_bot_running_shows_emoji(self):
        todo = _make_todo()
        label = _render_label(todo, bot_running={1})
        assert "💭" in label.plain

    def test_bot_desc_shows_robot(self):
        from todo_cli.tui import BOT_DIVIDER
        todo = _make_todo(desc=f"some text{BOT_DIVIDER}response")
        label = _render_label(todo)
        assert "🤖" in label.plain
