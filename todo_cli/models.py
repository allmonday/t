from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Todo:
    id: int
    text: str
    done: bool
    parent: int | None
    created: str
    done_at: str | None
    deleted_at: str | None


@dataclass
class FlatRow:
    """树扁平化后的一行，供 CLI 渲染。"""

    todo: Todo
    depth: int
    prefix: str
    has_children: bool
    is_last_child: bool
