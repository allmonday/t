from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import DeclarativeBase

# ── Layer 1: SQLAlchemy ORM Models ──


class Base(DeclarativeBase):
    pass


class TodoORM(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    done = Column(Integer, nullable=False, default=0)
    parent = Column(Integer, ForeignKey("todos.id"), nullable=True)
    created = Column(Text, nullable=False)
    done_at = Column(Text, nullable=True)
    deleted_at = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_todos_parent", "parent"),
        Index("idx_todos_active", "deleted_at"),
    )


class AuditORM(Base):
    __tablename__ = "audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    todo_id = Column(Integer, nullable=False)
    details = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_audit_time", "timestamp"),
    )


# ── Layer 2: Pydantic Entity ──


class TodoEntity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    done: bool = False
    parent: Optional[int] = None
    created: str = ""
    done_at: Optional[str] = None
    deleted_at: Optional[str] = None


# ── Layer 3: 渲染辅助 ──


@dataclass
class FlatRow:
    """树扁平化后的一行，供 CLI/TUI 渲染。"""

    todo: TodoEntity
    depth: int
    prefix: str
    has_children: bool
    is_last_child: bool
