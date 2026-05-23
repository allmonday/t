"""Direct client: local mode, calls TodoStore/PomodoroStore directly."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker

from .models import PomodoroSessionEntity, TodoEntity
from .store import PomodoroStore, TodoStore


class _DirectPomodoroClient:
    """Local pomodoro client, delegates to PomodoroStore."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._factory = session_factory

    async def record_session(
        self,
        started_at: str,
        finished_at: str,
        phase: str,
        duration_seconds: int,
        completed: bool,
    ) -> PomodoroSessionEntity:
        store = PomodoroStore(self._factory)
        return await store.record_session(
            started_at, finished_at, phase, duration_seconds, completed
        )

    async def today_sessions(self) -> list[PomodoroSessionEntity]:
        store = PomodoroStore(self._factory)
        return await store.today_sessions()


class DirectClient:
    """Local client: calls TodoStore/PomodoroStore directly, no network."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._factory = session_factory
        self._pomodoro: _DirectPomodoroClient | None = None

    async def close(self) -> None:
        pass  # nothing to close

    @property
    def pomodoro(self) -> _DirectPomodoroClient:
        if self._pomodoro is None:
            self._pomodoro = _DirectPomodoroClient(self._factory)
        return self._pomodoro

    # ── queries ──

    async def list_active(self) -> list[TodoEntity]:
        store = TodoStore(self._factory)
        return await store.list_active()

    async def get(self, todo_id: int) -> TodoEntity | None:
        store = TodoStore(self._factory)
        return await store.get(todo_id)

    async def get_children(self, todo_id: int) -> list[TodoEntity]:
        store = TodoStore(self._factory)
        return await store.get_children(todo_id)

    async def get_descendants(self, todo_id: int) -> list[TodoEntity]:
        store = TodoStore(self._factory)
        return await store.get_descendants(todo_id)

    async def has_children(self, todo_id: int) -> bool:
        store = TodoStore(self._factory)
        return await store.has_children(todo_id)

    # ── mutations ──

    async def add(self, text: str, parent_id: int | None = None, desc: str | None = None) -> TodoEntity:
        store = TodoStore(self._factory)
        return await store.add(text, parent_id, desc)

    async def update_text(self, todo_id: int, new_text: str) -> bool:
        store = TodoStore(self._factory)
        return await store.update_text(todo_id, new_text)

    async def update_desc(self, todo_id: int, new_desc: str) -> bool:
        store = TodoStore(self._factory)
        return await store.update_desc(todo_id, new_desc)

    async def toggle(self, todo_id: int) -> bool:
        store = TodoStore(self._factory)
        return await store.toggle(todo_id)

    async def toggle_pin(self, todo_id: int) -> bool:
        store = TodoStore(self._factory)
        return await store.toggle_pin(todo_id)

    async def delete(self, todo_id: int) -> int:
        store = TodoStore(self._factory)
        return await store.delete(todo_id)

    async def get_audit(self, limit: int = 50, action: str | None = None) -> list[dict]:
        store = TodoStore(self._factory)
        return await store.get_audit(limit, action)
