"""HTTP client for todo server. Replaces direct TodoStore/PomodoroStore usage."""
from __future__ import annotations

import httpx

from .models import PomodoroSessionEntity, TodoEntity


class TodoClientError(Exception):
    """Client-side error wrapping HTTP errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def is_auth_error(self) -> bool:
        return self.status_code == 401

    @property
    def is_network_error(self) -> bool:
        return self.status_code is None

    @property
    def is_not_found(self) -> bool:
        return self.status_code == 404


class PomodoroClient:
    """Async HTTP client that mirrors PomodoroStore's public API."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    async def record_session(
        self,
        started_at: str,
        finished_at: str,
        phase: str,
        duration_seconds: int,
        completed: bool,
    ) -> PomodoroSessionEntity:
        r = await self._client.post("/api/pomodoro/sessions", json={
            "started_at": started_at,
            "finished_at": finished_at,
            "phase": phase,
            "duration_seconds": duration_seconds,
            "completed": completed,
        })
        _handle_error(r)
        return PomodoroSessionEntity(**r.json())

    async def today_sessions(self) -> list[PomodoroSessionEntity]:
        r = await self._client.get("/api/pomodoro/sessions/today")
        _handle_error(r)
        return [PomodoroSessionEntity(**item) for item in r.json()["items"]]


def _handle_error(response: httpx.Response) -> None:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise TodoClientError(detail, response.status_code)


class TodoClient:
    """Async HTTP client that mirrors TodoStore's public API."""

    def __init__(self, base_url: str, api_token: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=10.0,
        )
        self._pomodoro: PomodoroClient | None = None

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def pomodoro(self) -> PomodoroClient:
        if self._pomodoro is None:
            self._pomodoro = PomodoroClient(self._client)
        return self._pomodoro

    # ── queries ──

    async def list_active(self) -> list[TodoEntity]:
        r = await self._client.get("/api/todos")
        _handle_error(r)
        return [TodoEntity(**item) for item in r.json()["items"]]

    async def get(self, todo_id: int) -> TodoEntity | None:
        r = await self._client.get(f"/api/todos/{todo_id}")
        if r.status_code == 404:
            return None
        _handle_error(r)
        return TodoEntity(**r.json())

    async def get_children(self, todo_id: int) -> list[TodoEntity]:
        r = await self._client.get(f"/api/todos/{todo_id}/children")
        _handle_error(r)
        return [TodoEntity(**item) for item in r.json()["items"]]

    async def get_descendants(self, todo_id: int) -> list[TodoEntity]:
        r = await self._client.get(f"/api/todos/{todo_id}/descendants")
        _handle_error(r)
        return [TodoEntity(**item) for item in r.json()["items"]]

    async def has_children(self, todo_id: int) -> bool:
        r = await self._client.get(f"/api/todos/{todo_id}/has-children")
        _handle_error(r)
        return r.json()["has_children"]

    # ── mutations ──

    async def add(self, text: str, parent_id: int | None = None, desc: str | None = None) -> TodoEntity:
        r = await self._client.post("/api/todos", json={
            "text": text, "parent_id": parent_id, "desc": desc,
        })
        _handle_error(r)
        return TodoEntity(**r.json())

    async def update_text(self, todo_id: int, new_text: str) -> bool:
        r = await self._client.put(f"/api/todos/{todo_id}/text", json={"text": new_text})
        _handle_error(r)
        return r.json()["success"]

    async def update_desc(self, todo_id: int, new_desc: str) -> bool:
        r = await self._client.put(f"/api/todos/{todo_id}/desc", json={"desc": new_desc})
        _handle_error(r)
        return r.json()["success"]

    async def toggle(self, todo_id: int) -> bool:
        r = await self._client.put(f"/api/todos/{todo_id}/toggle")
        _handle_error(r)
        return r.json()["success"]

    async def toggle_pin(self, todo_id: int) -> bool:
        r = await self._client.put(f"/api/todos/{todo_id}/pin")
        _handle_error(r)
        return r.json()["success"]

    async def delete(self, todo_id: int) -> int:
        r = await self._client.delete(f"/api/todos/{todo_id}")
        _handle_error(r)
        return r.json()["count"]

    async def get_audit(self, limit: int = 50, action: str | None = None) -> list[dict]:
        params: dict = {"limit": limit}
        if action:
            params["action"] = action
        r = await self._client.get("/api/audit", params=params)
        _handle_error(r)
        return r.json()["items"]
