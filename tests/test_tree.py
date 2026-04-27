from __future__ import annotations

from datetime import datetime, timedelta

from todo_cli.models import TodoEntity as Todo
from todo_cli.tree import (
    _collect_subtree,
    build_children_map,
    filter_by_roots,
    filter_todos,
    flatten_tree,
    format_time,
    get_roots,
)

from .conftest import _make_todo


# ── build_children_map ──


class TestBuildChildrenMap:
    def test_basic(self, sample_todos):
        m = build_children_map(sample_todos)
        assert [t.id for t in m[None]] == [1, 2, 3]
        assert [t.id for t in m[1]] == [4, 5]
        assert [t.id for t in m[8]] == [9]
        assert 4 not in m  # 叶节点不是任何人的 parent

    def test_empty(self, empty_todos):
        assert build_children_map(empty_todos) == {}

    def test_all_roots(self):
        todos = [_make_todo(1, "a"), _make_todo(2, "b")]
        m = build_children_map(todos)
        assert set(m) == {None}
        assert len(m[None]) == 2


# ── get_roots ──


class TestGetRoots:
    def test_basic(self, sample_todos):
        roots = get_roots(sample_todos)
        assert [t.id for t in roots] == [1, 2, 3]

    def test_empty(self, empty_todos):
        assert get_roots(empty_todos) == []

    def test_no_roots(self):
        todos = [_make_todo(1, "a", parent=99)]
        assert get_roots(todos) == []


# ── _collect_subtree ──


class TestCollectSubtree:
    def test_leaf(self, sample_todos):
        cm = build_children_map(sample_todos)
        todo_4 = next(t for t in sample_todos if t.id == 4)
        result = _collect_subtree(cm, todo_4)
        assert {t.id for t in result} == {4}

    def test_with_children(self, sample_todos):
        cm = build_children_map(sample_todos)
        todo_3 = next(t for t in sample_todos if t.id == 3)
        result = _collect_subtree(cm, todo_3)
        assert {t.id for t in result} == {3, 8, 9}

    def test_root_with_done_children(self, sample_todos):
        cm = build_children_map(sample_todos)
        todo_2 = next(t for t in sample_todos if t.id == 2)
        result = _collect_subtree(cm, todo_2)
        assert {t.id for t in result} == {2, 6, 7}


# ── filter_by_roots ──


class TestFilterByRoots:
    def test_none_returns_all(self, sample_todos):
        assert filter_by_roots(sample_todos, None) == sample_todos

    def test_done(self, sample_todos):
        result = filter_by_roots(sample_todos, True)
        assert {t.id for t in result} == {2, 6, 7}

    def test_pending(self, sample_todos):
        result = filter_by_roots(sample_todos, False)
        assert {t.id for t in result} == {1, 3, 4, 5, 8, 9}


# ── filter_todos ──


class TestFilterTodos:
    def test_default(self, sample_todos):
        assert filter_todos(sample_todos) == sample_todos

    def test_done(self, sample_todos):
        result = filter_todos(sample_todos, filter_done=True)
        assert {t.id for t in result} == {2, 6, 7}

    def test_pending(self, sample_todos):
        result = filter_todos(sample_todos, filter_done=False)
        assert {t.id for t in result} == {1, 3, 4, 5, 8, 9}

    def test_hide_stale(self, stale_todos):
        result = filter_todos(stale_todos, hide_stale=True, stale_days=2)
        # 过期完成根(#2)及其子(#4)被移除
        assert {t.id for t in result} == {1, 3}

    def test_stale_and_done_combined(self, stale_todos):
        result = filter_todos(stale_todos, filter_done=True, hide_stale=True, stale_days=2)
        # done=True → {1,2,4}; stale 过滤 → 去掉 {2,4}; 剩下 {1}
        assert {t.id for t in result} == {1}

    def test_hide_stale_no_stale_items(self, sample_todos):
        # sample_todos 的 done_at 都是今天，不会被 stale 过滤
        result = filter_todos(sample_todos, hide_stale=True, stale_days=2)
        assert {t.id for t in result} == {t.id for t in sample_todos}

    def test_empty(self, empty_todos):
        assert filter_todos(empty_todos) == []

    def test_stale_done_at_none(self):
        """done=True 但 done_at=None 的根不应被 stale 过滤。"""
        todos = [_make_todo(1, "无完成时间", True, None, done_at=None)]
        result = filter_todos(todos, hide_stale=True, stale_days=2)
        assert len(result) == 1


# ── flatten_tree ──


class TestFlattenTree:
    def test_basic(self, sample_todos):
        rows = flatten_tree(sample_todos)
        assert len(rows) == 9

    def test_depth(self, sample_todos):
        rows = flatten_tree(sample_todos)
        by_id = {r.todo.id: r for r in rows}
        assert by_id[1].depth == 0
        assert by_id[4].depth == 1
        assert by_id[9].depth == 2

    def test_collapsed(self, sample_todos):
        rows = flatten_tree(sample_todos, collapsed={1})
        ids = {r.todo.id for r in rows}
        assert 1 in ids
        assert 4 not in ids
        assert 5 not in ids

    def test_empty(self, empty_todos):
        assert flatten_tree(empty_todos) == []

    def test_single(self, single_todo):
        rows = flatten_tree(single_todo)
        assert len(rows) == 1
        assert rows[0].depth == 0
        assert rows[0].has_children is False

    def test_prefix_connectors(self):
        """验证树形连接符和 is_last_child。"""
        root = _make_todo(1, "root")
        c1 = _make_todo(2, "c1", parent=1)
        c2 = _make_todo(3, "c2", parent=1)
        c3 = _make_todo(4, "c3", parent=1)
        rows = flatten_tree([root, c1, c2, c3])
        by_id = {r.todo.id: r for r in rows}
        assert "├── " in by_id[2].prefix
        assert "├── " in by_id[3].prefix
        assert "└── " in by_id[4].prefix
        assert by_id[2].is_last_child is False
        assert by_id[3].is_last_child is False
        assert by_id[4].is_last_child is True


# ── format_time ──


class TestFormatTime:
    def test_today(self):
        now = datetime.now().isoformat()
        assert format_time(now) == "today"

    def test_yesterday(self):
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        assert format_time(yesterday) == "yesterday"

    def test_same_year(self):
        year = datetime.now().year
        assert format_time(f"{year}-03-15T10:00:00") == "03/15"

    def test_other_year(self):
        assert format_time("2024-06-15T10:00:00") == "2024/06/15"

    def test_invalid(self):
        assert format_time("not-a-date") == ""

    def test_empty(self):
        assert format_time("") == ""
