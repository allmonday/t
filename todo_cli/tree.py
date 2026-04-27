from __future__ import annotations

import unicodedata
from datetime import datetime

from .models import FlatRow, Todo


def build_children_map(todos: list[Todo]) -> dict[int | None, list[Todo]]:
    """构建 parent_id → children 列表映射。"""
    children_map: dict[int | None, list[Todo]] = {}
    for t in todos:
        children_map.setdefault(t.parent, []).append(t)
    return children_map


def get_roots(todos: list[Todo]) -> list[Todo]:
    return [t for t in todos if t.parent is None]


def filter_by_roots(todos: list[Todo], filter_done: bool | None) -> list[Todo]:
    """按根任务 done 状态过滤，返回匹配的根及其所有子孙。"""
    if filter_done is None:
        return todos
    children_map = build_children_map(todos)
    roots = [t for t in children_map.get(None, []) if t.done == filter_done]
    result: list[Todo] = []

    def collect(node: Todo) -> None:
        result.append(node)
        for child in children_map.get(node.id, []):
            collect(child)

    for root in roots:
        collect(root)
    return result


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


def display_width(s: str) -> int:
    """计算字符串在终端中的显示宽度（CJK 字符占 2 列）。"""
    w = 0
    for ch in s:
        eaw = unicodedata.east_asian_width(ch)
        w += 2 if eaw in ("F", "W") else 1
    return w


def truncate_to_width(s: str, max_width: int) -> str:
    """截断字符串到指定的终端显示宽度。"""
    w = 0
    for i, ch in enumerate(s):
        cw = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if w + cw > max_width:
            return s[:i] + "…"
        w += cw
    return s


def format_time(iso_str: str) -> str:
    """ISO 8601 → 'today' / 'yesterday' / 'MM/DD'"""
    try:
        dt = datetime.fromisoformat(iso_str)
        today = datetime.now().date()
        delta = (today - dt.date()).days
        if delta == 0:
            return "today"
        elif delta == 1:
            return "yesterday"
        else:
            return dt.strftime("%m/%d")
    except (ValueError, TypeError):
        return ""
