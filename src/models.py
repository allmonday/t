"""Phase 1: SQLModel entity definitions.

Pure entity fields + Relationship declarations (no methods).

Entity graph:
    Todo ──1:N(self)──→ Todo       (parent_id, tree structure)
    Todo ──1:N──→ Audit
    PomodoroSession                  (independent)
"""
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

from src.db import async_session


class BaseEntity(SQLModel):
    """All entities inherit from this base class for shared metadata discovery."""


class Todo(BaseEntity, table=True):
    """任务项，支持树形结构（parent_id 自引用）。"""

    id: int | None = Field(default=None, primary_key=True, description="任务唯一标识")
    text: str = Field(description="任务标题")
    desc: str | None = Field(default=None, description="任务描述（Markdown）")
    done: bool = Field(default=False, description="是否已完成")
    parent_id: int | None = Field(
        default=None, foreign_key="todo.id", description="父任务 ID（树形结构）"
    )
    pinned: bool = Field(default=False, description="是否置顶（仅根节点有效）")
    created: str = Field(default="", description="创建时间 ISO 格式")
    done_at: str | None = Field(default=None, description="完成时间")
    deleted_at: str | None = Field(default=None, description="软删除时间")

    # ORM relationships (noload)
    children: list["Todo"] = Relationship(
        back_populates="parent",
        sa_relationship_kwargs={"lazy": "noload"},
    )
    parent: Optional["Todo"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"lazy": "noload", "remote_side": "Todo.id"},
    )
    audit_logs: list["Audit"] = Relationship(
        back_populates="todo",
        sa_relationship_kwargs={"lazy": "noload"},
    )


class Audit(BaseEntity, table=True):
    """审计日志，记录任务操作历史。"""

    id: int | None = Field(default=None, primary_key=True, description="审计记录标识")
    timestamp: str = Field(description="操作时间 ISO 格式")
    action: str = Field(description="操作类型：add/edit/toggle/delete/...")
    todo_id: int = Field(foreign_key="todo.id", description="关联任务 ID")
    details: str | None = Field(default=None, description="JSON 格式操作详情")

    # ORM relationships (noload)
    todo: Optional["Todo"] = Relationship(
        back_populates="audit_logs",
        sa_relationship_kwargs={"lazy": "noload"},
    )


class PomodoroSession(BaseEntity, table=True):
    """番茄钟会话记录，独立于任务。"""

    id: int | None = Field(default=None, primary_key=True, description="会话唯一标识")
    started_at: str = Field(description="开始时间 ISO 格式")
    finished_at: str = Field(description="结束时间 ISO 格式")
    phase: str = Field(description="阶段：focus / break / long_break")
    duration_seconds: int = Field(description="持续秒数")
    completed: bool = Field(default=True, description="是否完整完成")


# ── Method mounting (Phase 2) ─────────────────────────────────────────


def mount_method():
    """挂载 service methods 到 entity classes。需在外部显式调用。"""
    import functools

    from nexusx import mutation, query
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

    def _mount(entity, fn, decorator):
        @functools.wraps(fn)
        async def wrapper(cls, *args, **kwargs):
            return await fn(*args, **kwargs)
        setattr(entity, fn.__name__, decorator(wrapper))

    # Todo queries
    _mount(Todo, list_todos, query)
    _mount(Todo, get_todo, query)
    _mount(Todo, get_children, query)
    _mount(Todo, get_descendants, query)
    _mount(Todo, has_children, query)
    # Todo mutations
    _mount(Todo, add_todo, mutation)
    _mount(Todo, update_text, mutation)
    _mount(Todo, update_desc, mutation)
    _mount(Todo, toggle_todo, mutation)
    _mount(Todo, toggle_pin, mutation)
    _mount(Todo, delete_todo, mutation)
    # Audit queries
    _mount(Audit, get_audit, query)
    # PomodoroSession queries & mutations
    _mount(PomodoroSession, today_sessions, query)
    _mount(PomodoroSession, record_session, mutation)


# ── ErManager + Resolver (Phase 3) ──────────────────────────────────────

from nexusx import ErManager  # noqa: E402

er = ErManager(
    entities=[Todo, Audit, PomodoroSession],
    session_factory=async_session,
)
Resolver = er.create_resolver()
