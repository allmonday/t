from __future__ import annotations

from sqlalchemy import text

from todo_cli.store import TodoStore


# ── lifecycle ──


class TestLifecycle:
    async def test_context_manager(self, store):
        assert store.session_factory is not None


# ── add ──


class TestAdd:
    async def test_root(self, store: TodoStore):
        todo = await store.add("任务A")
        assert todo.text == "任务A"
        assert todo.parent is None
        assert todo.done is False

    async def test_child(self, store: TodoStore):
        parent = await store.add("父")
        child = await store.add("子", parent_id=parent.id)
        assert child.parent == parent.id

    async def test_invalid_parent(self, store: TodoStore):
        import pytest
        with pytest.raises(ValueError, match="not found"):
            await store.add("x", parent_id=999)

    async def test_auto_increment(self, store: TodoStore):
        a = await store.add("a")
        b = await store.add("b")
        assert b.id > a.id


# ── update_text ──


class TestUpdateText:
    async def test_success(self, store: TodoStore):
        todo = await store.add("旧文本")
        assert await store.update_text(todo.id, "新文本") is True
        assert (await store.get(todo.id)).text == "新文本"

    async def test_nonexistent(self, store: TodoStore):
        assert await store.update_text(999, "x") is False


# ── toggle + _bubble_up ──


class TestToggle:
    async def test_leaf_done(self, store: TodoStore):
        parent = await store.add("父")
        child = await store.add("子", parent_id=parent.id)
        assert await store.toggle(child.id) is True
        updated = await store.get(child.id)
        assert updated.done is True
        assert updated.done_at is not None

    async def test_undone(self, store: TodoStore):
        todo = await store.add("任务")
        await store.toggle(todo.id)
        await store.toggle(todo.id)
        updated = await store.get(todo.id)
        assert updated.done is False
        assert updated.done_at is None

    async def test_nonexistent(self, store: TodoStore):
        assert await store.toggle(999) is False

    async def test_parent_fails(self, store: TodoStore):
        parent = await store.add("父")
        await store.add("子", parent_id=parent.id)
        assert await store.toggle(parent.id) is False


class TestBubbleUp:
    """_bubble_up 是私有方法，通过 toggle 间接测试。"""

    async def test_all_children_done(self, store: TodoStore):
        parent = await store.add("父")
        c1 = await store.add("c1", parent_id=parent.id)
        c2 = await store.add("c2", parent_id=parent.id)
        await store.toggle(c1.id)
        await store.toggle(c2.id)
        p = await store.get(parent.id)
        assert p.done is True
        assert p.done_at is not None

    async def test_partial(self, store: TodoStore):
        parent = await store.add("父")
        c1 = await store.add("c1", parent_id=parent.id)
        await store.add("c2", parent_id=parent.id)
        await store.toggle(c1.id)
        assert (await store.get(parent.id)).done is False

    async def test_undone_cascades(self, store: TodoStore):
        parent = await store.add("父")
        c1 = await store.add("c1", parent_id=parent.id)
        c2 = await store.add("c2", parent_id=parent.id)
        await store.toggle(c1.id)
        await store.toggle(c2.id)
        assert (await store.get(parent.id)).done is True
        # 取消一个子节点
        await store.toggle(c1.id)
        assert (await store.get(parent.id)).done is False
        assert (await store.get(parent.id)).done_at is None

    async def test_multi_level(self, store: TodoStore):
        """三层结构：所有叶完成后祖父自动 done。"""
        root = await store.add("祖父")
        mid = await store.add("父", parent_id=root.id)
        leaf = await store.add("叶", parent_id=mid.id)
        await store.toggle(leaf.id)
        assert (await store.get(mid.id)).done is True
        assert (await store.get(root.id)).done is True


# ── delete ──


class TestDelete:
    async def test_leaf(self, store: TodoStore):
        todo = await store.add("任务")
        assert await store.delete(todo.id) == 1
        assert await store.get(todo.id) is None

    async def test_cascades(self, store: TodoStore):
        parent = await store.add("父")
        c1 = await store.add("c1", parent_id=parent.id)
        c2 = await store.add("c2", parent_id=parent.id)
        count = await store.delete(parent.id)
        assert count == 3
        assert await store.get(parent.id) is None
        assert await store.get(c1.id) is None
        assert await store.get(c2.id) is None

    async def test_nonexistent(self, store: TodoStore):
        assert await store.delete(999) == 0

    async def test_soft_not_hard(self, store: TodoStore):
        todo = await store.add("任务")
        await store.delete(todo.id)
        # 直接查 SQL 确认行仍在
        async with store.session_factory() as session:
            row = await session.execute(
                text("SELECT deleted_at FROM todos WHERE id = :id"),
                {"id": todo.id},
            )
            r = row.fetchone()
            assert r.deleted_at is not None


# ── get_descendants ──


class TestGetDescendants:
    async def test_deep(self, store: TodoStore):
        root = await store.add("root")
        c1 = await store.add("c1", parent_id=root.id)
        c1a = await store.add("c1a", parent_id=c1.id)
        c1b = await store.add("c1b", parent_id=c1.id)
        descs = await store.get_descendants(root.id)
        assert {t.id for t in descs} == {c1.id, c1a.id, c1b.id}

    async def test_leaf(self, store: TodoStore):
        todo = await store.add("leaf")
        assert await store.get_descendants(todo.id) == []

    async def test_excludes_deleted(self, store: TodoStore):
        root = await store.add("root")
        c1 = await store.add("c1", parent_id=root.id)
        c2 = await store.add("c2", parent_id=root.id)
        await store.delete(c2.id)
        descs = await store.get_descendants(root.id)
        assert {t.id for t in descs} == {c1.id}
