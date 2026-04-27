from __future__ import annotations

import pytest

from todo_cli.store import TodoStore


# ── lifecycle ──


class TestLifecycle:
    def test_require_conn_raises(self):
        s = TodoStore(":memory:")
        with pytest.raises(RuntimeError, match="not connected"):
            s.add("should fail")

    def test_context_manager(self):
        with TodoStore(":memory:") as s:
            assert s.conn is not None
        assert s.conn is None

    def test_seed_populates_data(self):
        s = TodoStore(":memory:")
        s.connect()
        todos = s.list_active()
        assert len(todos) > 0
        s.close()


# ── add ──


class TestAdd:
    def test_root(self, store):
        todo = store.add("任务A")
        assert todo.text == "任务A"
        assert todo.parent is None
        assert todo.done is False

    def test_child(self, store):
        parent = store.add("父")
        child = store.add("子", parent_id=parent.id)
        assert child.parent == parent.id

    def test_invalid_parent(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.add("x", parent_id=999)

    def test_auto_increment(self, store):
        a = store.add("a")
        b = store.add("b")
        assert b.id > a.id


# ── update_text ──


class TestUpdateText:
    def test_success(self, store):
        todo = store.add("旧文本")
        assert store.update_text(todo.id, "新文本") is True
        assert store.get(todo.id).text == "新文本"

    def test_nonexistent(self, store):
        assert store.update_text(999, "x") is False


# ── toggle + _bubble_up ──


class TestToggle:
    def test_leaf_done(self, store):
        parent = store.add("父")
        child = store.add("子", parent_id=parent.id)
        assert store.toggle(child.id) is True
        updated = store.get(child.id)
        assert updated.done is True
        assert updated.done_at is not None

    def test_undone(self, store):
        todo = store.add("任务")
        store.toggle(todo.id)
        store.toggle(todo.id)
        updated = store.get(todo.id)
        assert updated.done is False
        assert updated.done_at is None

    def test_nonexistent(self, store):
        assert store.toggle(999) is False

    def test_parent_fails(self, store):
        parent = store.add("父")
        store.add("子", parent_id=parent.id)
        assert store.toggle(parent.id) is False


class TestBubbleUp:
    """_bubble_up 是私有方法，通过 toggle 间接测试。"""

    def test_all_children_done(self, store):
        parent = store.add("父")
        c1 = store.add("c1", parent_id=parent.id)
        c2 = store.add("c2", parent_id=parent.id)
        store.toggle(c1.id)
        store.toggle(c2.id)
        p = store.get(parent.id)
        assert p.done is True
        assert p.done_at is not None

    def test_partial(self, store):
        parent = store.add("父")
        c1 = store.add("c1", parent_id=parent.id)
        store.add("c2", parent_id=parent.id)
        store.toggle(c1.id)
        assert store.get(parent.id).done is False

    def test_undone_cascades(self, store):
        parent = store.add("父")
        c1 = store.add("c1", parent_id=parent.id)
        c2 = store.add("c2", parent_id=parent.id)
        store.toggle(c1.id)
        store.toggle(c2.id)
        assert store.get(parent.id).done is True
        # 取消一个子节点
        store.toggle(c1.id)
        assert store.get(parent.id).done is False
        assert store.get(parent.id).done_at is None

    def test_multi_level(self, store):
        """三层结构：所有叶完成后祖父自动 done。"""
        root = store.add("祖父")
        mid = store.add("父", parent_id=root.id)
        leaf = store.add("叶", parent_id=mid.id)
        store.toggle(leaf.id)
        assert store.get(mid.id).done is True
        assert store.get(root.id).done is True


# ── delete ──


class TestDelete:
    def test_leaf(self, store):
        todo = store.add("任务")
        assert store.delete(todo.id) == 1
        assert store.get(todo.id) is None

    def test_cascades(self, store):
        parent = store.add("父")
        c1 = store.add("c1", parent_id=parent.id)
        c2 = store.add("c2", parent_id=parent.id)
        count = store.delete(parent.id)
        assert count == 3
        assert store.get(parent.id) is None
        assert store.get(c1.id) is None
        assert store.get(c2.id) is None

    def test_nonexistent(self, store):
        assert store.delete(999) == 0

    def test_soft_not_hard(self, store):
        todo = store.add("任务")
        store.delete(todo.id)
        # 直接查 SQL 确认行仍在
        row = store._require_conn().execute(
            "SELECT deleted_at FROM todos WHERE id = ?", (todo.id,)
        ).fetchone()
        assert row["deleted_at"] is not None


# ── get_descendants ──


class TestGetDescendants:
    def test_deep(self, store):
        root = store.add("root")
        c1 = store.add("c1", parent_id=root.id)
        c1a = store.add("c1a", parent_id=c1.id)
        c1b = store.add("c1b", parent_id=c1.id)
        descs = store.get_descendants(root.id)
        assert {t.id for t in descs} == {c1.id, c1a.id, c1b.id}

    def test_leaf(self, store):
        todo = store.add("leaf")
        assert store.get_descendants(todo.id) == []

    def test_excludes_deleted(self, store):
        root = store.add("root")
        c1 = store.add("c1", parent_id=root.id)
        c2 = store.add("c2", parent_id=root.id)
        store.delete(c2.id)
        descs = store.get_descendants(root.id)
        assert {t.id for t in descs} == {c1.id}
