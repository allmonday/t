"""API request/response schemas."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ..models import PomodoroSessionEntity, TodoEntity


# ── Todo requests ──


class TodoCreateRequest(BaseModel):
    text: str
    parent_id: Optional[int] = None
    desc: Optional[str] = None


class TodoUpdateTextRequest(BaseModel):
    text: str


class TodoUpdateDescRequest(BaseModel):
    desc: str


# ── Todo responses ──


class TodoListResponse(BaseModel):
    items: list[TodoEntity]


class TodoToggleResponse(BaseModel):
    success: bool


class TodoDeleteResponse(BaseModel):
    count: int


class HasChildrenResponse(BaseModel):
    has_children: bool


class DescendantsResponse(BaseModel):
    items: list[TodoEntity]


class AuditEntry(BaseModel):
    id: int
    timestamp: str
    action: str
    todo_id: int
    details: dict


class AuditListResponse(BaseModel):
    items: list[AuditEntry]


# ── Pomodoro requests ──


class PomodoroSessionCreateRequest(BaseModel):
    started_at: str
    finished_at: str
    phase: str
    duration_seconds: int
    completed: bool


# ── Pomodoro responses ──


class PomodoroSessionListResponse(BaseModel):
    items: list[PomodoroSessionEntity]
