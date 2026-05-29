"""Direct client: local mode, calls TodoStore/PomodoroStore directly."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker

from .models import PomodoroSessionEntity, TodoEntity
from .store import PomodoroStore, TodoStore


class DirectClient:
    """Local client: calls TodoStore/PomodoroStore directly, no network."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._todo_store = TodoStore(session_factory)
        self._pomo_store = PomodoroStore(session_factory)

    async def close(self) -> None:
        pass  # nothing to close

    @property
    def pomodoro(self) -> PomodoroStore:
        return self._pomo_store

    # ── queries ──

    async def list_active(self) -> list[TodoEntity]:
        return await self._todo_store.list_active()

    async def get(self, todo_id: int) -> TodoEntity | None:
        return await self._todo_store.get(todo_id)

    async def get_children(self, todo_id: int) -> list[TodoEntity]:
        return await self._todo_store.get_children(todo_id)

    async def get_descendants(self, todo_id: int) -> list[TodoEntity]:
        return await self._todo_store.get_descendants(todo_id)

    async def has_children(self, todo_id: int) -> bool:
        return await self._todo_store.has_children(todo_id)

    # ── mutations ──

    async def add(self, text: str, parent_id: int | None = None, desc: str | None = None) -> TodoEntity:
        return await self._todo_store.add(text, parent_id, desc)

    async def update_text(self, todo_id: int, new_text: str) -> bool:
        return await self._todo_store.update_text(todo_id, new_text)

    async def update_desc(self, todo_id: int, new_desc: str) -> bool:
        return await self._todo_store.update_desc(todo_id, new_desc)

    async def toggle(self, todo_id: int) -> bool:
        return await self._todo_store.toggle(todo_id)

    async def toggle_pin(self, todo_id: int) -> bool:
        return await self._todo_store.toggle_pin(todo_id)

    async def delete(self, todo_id: int) -> int:
        return await self._todo_store.delete(todo_id)

    async def get_audit(self, limit: int = 50, action: str | None = None) -> list[dict]:
        return await self._todo_store.get_audit(limit, action)
