from __future__ import annotations

import pytest

from todo_cli.store import TodoStore
from todo_cli.tui import TodoApp, TodoTree


@pytest.fixture
def store():
    s = TodoStore(":memory:")
    s.connect()
    conn = s._require_conn()
    conn.execute("DELETE FROM audit")
    conn.execute("DELETE FROM todos")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='todos'")
    yield s
    s.close()


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


@pytest.mark.asyncio
async def test_add_root_cursor_on_new_todo(store):
    store.add("existing task")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        # cursor starts on "TODO" root; press 'a' to add sibling,
        # which falls through to add_root since no todo is selected
        await pilot.press("a")
        await _type_and_submit(pilot, "new root")
        await pilot.pause()

        todo_id = _cursor_todo_id(app)
        assert todo_id is not None, "cursor should not be on root"
        todo = store.get(todo_id)
        assert todo.text == "new root"
        assert todo.parent is None


# ── add_sibling ──


@pytest.mark.asyncio
async def test_add_sibling_of_child(store):
    """child 的 sibling 应在同一 parent 下，光标选中新建项。"""
    root = store.add("root")
    child = store.add("child1", parent_id=root.id)
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        # navigate: root TODO -> root todo -> expand -> child1
        await pilot.press("j")      # to root todo
        await pilot.press("l")      # expand root todo
        await pilot.press("j")      # to child1
        assert _cursor_todo_id(app) == child.id

        await pilot.press("a")
        await _type_and_submit(pilot, "child2")
        await pilot.pause()

        todo_id = _cursor_todo_id(app)
        assert todo_id is not None, "cursor should not be on root"
        todo = store.get(todo_id)
        assert todo.text == "child2"
        assert todo.parent == root.id


# ── add_child ──


@pytest.mark.asyncio
async def test_add_child_under_root(store):
    root = store.add("root")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        # navigate to root todo
        await pilot.press("j")
        assert _cursor_todo_id(app) == root.id

        await pilot.press("tab")
        await _type_and_submit(pilot, "sub")
        await pilot.pause()

        todo_id = _cursor_todo_id(app)
        assert todo_id is not None, "cursor should not be on root"
        # add_child keeps cursor on parent
        assert todo_id == root.id

        children = store.get_children(root.id)
        assert len(children) == 1
        assert children[0].text == "sub"


@pytest.mark.asyncio
async def test_add_child_consecutive_keeps_expanded(store):
    """连续 Tab 添加子节点，父节点应保持展开，光标停在父节点上。"""
    root = store.add("root")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")      # to root todo
        assert _cursor_todo_id(app) == root.id

        # 第一次 Tab：叶子节点变为分支，应自动展开
        await pilot.press("tab")
        await _type_and_submit(pilot, "c1")
        await pilot.pause()

        assert _cursor_todo_id(app) == root.id
        assert len(store.get_children(root.id)) == 1

        # 第二次 Tab：父节点应保持展开，继续添加
        await pilot.press("tab")
        await _type_and_submit(pilot, "c2")
        await pilot.pause()

        assert _cursor_todo_id(app) == root.id
        assert len(store.get_children(root.id)) == 2


# ── delete ──


@pytest.mark.asyncio
async def test_delete_only_todo_cursor_at_root(store):
    """删除唯一的 todo 后，光标回到 root。"""
    store.add("only task")
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")      # select the todo
        await pilot.press("d")
        await pilot.press("y")
        await pilot.pause()
        assert _cursor_todo_id(app) is None


@pytest.mark.asyncio
async def test_delete_child_cursor_not_at_root(store):
    """删除一个 child 后，树还在，光标不在 root。"""
    root = store.add("root")
    store.add("c1", parent_id=root.id)
    c2 = store.add("c2", parent_id=root.id)
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")      # to root todo
        await pilot.press("l")      # expand
        await pilot.press("j")      # to c1
        await pilot.press("j")      # to c2
        assert _cursor_todo_id(app) == c2.id

        await pilot.press("d")
        await pilot.press("y")
        await pilot.pause()

        assert _cursor_todo_id(app) is not None, "cursor should not be on root after delete"


# ── toggle ──


@pytest.mark.asyncio
async def test_toggle_preserves_cursor(store):
    root = store.add("root")
    child = store.add("child", parent_id=root.id)
    app = TodoApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")      # to root todo
        await pilot.press("l")      # expand
        await pilot.press("j")      # to child
        assert _cursor_todo_id(app) == child.id

        await pilot.press("space")
        await pilot.pause()

        assert _cursor_todo_id(app) == child.id
        assert store.get(child.id).done is True
