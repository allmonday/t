from __future__ import annotations

from datetime import datetime, timedelta

from .models import FlatRow, TodoEntity as Todo


def build_children_map(todos: list[Todo]) -> dict[int | None, list[Todo]]:
    """构建 parent_id → children 列表映射。"""
    children_map: dict[int | None, list[Todo]] = {}
    for t in todos:
        children_map.setdefault(t.parent, []).append(t)
    return children_map


def count_descendants(children_map: dict[int | None, list[Todo]]) -> dict[int, tuple[int, int]]:
    """返回 {todo_id: (done_count, total_count)}，叶子节点不包含在结果中。"""
    cache: dict[int, tuple[int, int]] = {}

    def _count(node_id: int) -> tuple[int, int]:
        if node_id in cache:
            return cache[node_id]
        children = children_map.get(node_id, [])
        done = 0
        total = 0
        for c in children:
            total += 1
            if c.done:
                done += 1
            cd, ct = _count(c.id)
            done += cd
            total += ct
        cache[node_id] = (done, total)
        return done, total

    for todo_id in children_map:
        if todo_id is not None:
            _count(todo_id)

    return {tid: counts for tid, counts in cache.items() if counts[1] > 0}


def get_roots(todos: list[Todo]) -> list[Todo]:
    return [t for t in todos if t.parent is None]


def _collect_subtree(children_map: dict[int | None, list[Todo]], root: Todo) -> list[Todo]:
    """收集以 root 为根的整棵子树。"""
    result: list[Todo] = []
    stack = [root]
    while stack:
        node = stack.pop()
        result.append(node)
        stack.extend(children_map.get(node.id, []))
    return result


def filter_by_roots(todos: list[Todo], filter_done: bool | None) -> list[Todo]:
    """按根任务 done 状态过滤，返回匹配的根及其所有子孙。"""
    if filter_done is None:
        return todos
    children_map = build_children_map(todos)
    roots = [t for t in children_map.get(None, []) if t.done == filter_done]
    result: list[Todo] = []
    for root in roots:
        result.extend(_collect_subtree(children_map, root))
    return result


def filter_todos(
    todos: list[Todo],
    filter_done: bool | None = None,
    hide_stale: bool = False,
    stale_days: int = 2,
) -> list[Todo]:
    """统一过滤：按根任务 done 状态 + stale 隐藏。返回过滤后的 todo 列表。"""
    children_map = build_children_map(todos)

    keep_ids: set[int] | None = None

    # 按 done 状态过滤
    if filter_done is not None:
        matched_roots = {t.id for t in children_map.get(None, []) if t.done == filter_done}
        keep_ids = set()
        for rid in matched_roots:
            for node in _collect_subtree(children_map, next(t for t in todos if t.id == rid)):
                keep_ids.add(node.id)
        # Pending 模式：迭代剪掉已完成的叶子节点
        if filter_done is False:
            # 基于 keep_ids 重建 children 关系
            kept_todos = [t for t in todos if t.id in keep_ids]
            changed = True
            while changed:
                changed = False
                parent_ids = {t.parent for t in kept_todos}
                done_leaves = {
                    t.id for t in kept_todos
                    if t.done and t.id not in parent_ids
                }
                if done_leaves:
                    keep_ids -= done_leaves
                    kept_todos = [t for t in kept_todos if t.id not in done_leaves]
                    changed = True

    # 按 stale 过滤
    if hide_stale:
        cutoff = (datetime.now() - timedelta(days=stale_days)).isoformat()
        stale_root_ids = {
            t.id for t in children_map.get(None, [])
            if t.done and t.done_at and t.done_at < cutoff
        }
        remove_ids: set[int] = set()
        for rid in stale_root_ids:
            for node in _collect_subtree(children_map, next(t for t in todos if t.id == rid)):
                remove_ids.add(node.id)
        if keep_ids is not None:
            keep_ids -= remove_ids
        else:
            keep_ids = {t.id for t in todos} - remove_ids

    if keep_ids is not None:
        return [t for t in todos if t.id in keep_ids]
    return todos


def flatten_tree(todos: list[Todo], collapsed: set[int] | None = None) -> list[FlatRow]:
    """将 todo 列表扁平化为带缩进前缀的行列表。"""
    if collapsed is None:
        collapsed = set()
    children_map = build_children_map(todos)
    rows: list[FlatRow] = []

    def walk(node: Todo, depth: int, parent_prefixes: list[str]) -> None:
        children = children_map.get(node.id, [])
        has_children = len(children) > 0
        is_last = False
        if node.parent is not None:
            siblings = children_map.get(node.parent, [])
            is_last = siblings[-1].id == node.id if siblings else False
        prefix = "".join(parent_prefixes)
        rows.append(FlatRow(
            todo=node,
            depth=depth,
            prefix=prefix,
            has_children=has_children,
            is_last_child=is_last,
        ))
        if node.id in collapsed or not has_children:
            return
        for i, child in enumerate(children):
            is_child_last = i == len(children) - 1
            if depth == 0:
                child_prefix: list[str] = []
            else:
                continuation = "    " if is_last else "│   "
                child_prefix = parent_prefixes + [continuation]
            connector = "└── " if is_child_last else "├── "
            walk(child, depth + 1, child_prefix + [connector])

    for root in children_map.get(None, []):
        walk(root, 0, [])

    return rows


def format_time(iso_str: str) -> str:
    """ISO 8601 → '' (today) / '+1d' / '+2d' / … / 'MM/DD' / 'YYYY/MM/DD'"""
    try:
        dt = datetime.fromisoformat(iso_str)
        today = datetime.now().date()
        delta = (today - dt.date()).days
        if delta == 0:
            return ""
        elif delta <= 30:
            return f"+{delta}d"
        elif dt.year == today.year:
            return dt.strftime("%m/%d")
        else:
            return dt.strftime("%Y/%m/%d")
    except (ValueError, TypeError):
        return ""
