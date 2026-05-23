"""Remote WebSocket client: connects to a remote todo server via WebSocket."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Callable

import websockets

from .models import PomodoroSessionEntity, TodoEntity

logger = logging.getLogger(__name__)


class ClientError(Exception):
    """Error from remote server."""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code

    @property
    def is_not_found(self) -> bool:
        return self.error_code == "not_found"


class _WSClient:
    """Low-level WebSocket client with request-response correlation."""

    def __init__(
        self,
        url: str,
        api_token: str | None = None,
    ) -> None:
        self._url = url
        self._token = api_token
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._listener_task: asyncio.Task | None = None
        self._on_broadcast: Callable[[dict], Any] | None = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to server and start background listener."""
        url = self._url
        if self._token:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}token={self._token}"

        self._ws = await websockets.connect(url, proxy=None)
        self._connected = True
        self._listener_task = asyncio.create_task(self._listener())

    async def close(self) -> None:
        self._connected = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        # Cancel any pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def request(self, msg_type: str, data: dict | None = None, timeout: float = 10.0) -> dict:
        """Send request and wait for correlated response."""
        if not self._ws or not self._connected:
            raise ClientError("Not connected")

        req_id = uuid.uuid4().hex[:16]
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[req_id] = future

        msg = {"type": msg_type, "req_id": req_id, "data": data or {}}
        await self._ws.send(json.dumps(msg))

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise ClientError("Request timed out")

    def on_broadcast(self, callback: Callable[[dict], Any]) -> None:
        self._on_broadcast = callback

    async def _listener(self) -> None:
        """Background task: receive messages and route them."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "response":
                    req_id = msg.get("req_id", "")
                    future = self._pending.pop(req_id, None)
                    if future and not future.done():
                        if msg.get("ok"):
                            future.set_result(msg.get("data", {}))
                        else:
                            err = ClientError(
                                msg.get("error", "Unknown error"),
                                msg.get("error_code"),
                            )
                            future.set_exception(err)
                elif msg_type == "broadcast":
                    if self._on_broadcast:
                        try:
                            result = self._on_broadcast(msg)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            logger.exception("Broadcast callback error")
        except websockets.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("WS listener error")
        finally:
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ClientError("Connection lost"))
            self._pending.clear()


class _RemotePomodoroClient:
    """Remote pomodoro client via WebSocket."""

    def __init__(self, ws: _WSClient) -> None:
        self._ws = ws

    async def record_session(
        self,
        started_at: str,
        finished_at: str,
        phase: str,
        duration_seconds: int,
        completed: bool,
    ) -> PomodoroSessionEntity:
        data = await self._ws.request("pomodoro.record_session", {
            "started_at": started_at,
            "finished_at": finished_at,
            "phase": phase,
            "duration_seconds": duration_seconds,
            "completed": completed,
        })
        return PomodoroSessionEntity(**data)

    async def today_sessions(self) -> list[PomodoroSessionEntity]:
        data = await self._ws.request("pomodoro.today_sessions")
        return [PomodoroSessionEntity(**item) for item in data["items"]]


class RemoteClient:
    """Remote client: communicates with server via WebSocket."""

    def __init__(self, url: str, api_token: str | None = None) -> None:
        self._ws = _WSClient(url, api_token)
        self._pomodoro: _RemotePomodoroClient | None = None

    async def connect(self) -> None:
        await self._ws.connect()

    async def close(self) -> None:
        await self._ws.close()

    @property
    def pomodoro(self) -> _RemotePomodoroClient:
        if self._pomodoro is None:
            self._pomodoro = _RemotePomodoroClient(self._ws)
        return self._pomodoro

    def set_broadcast_handler(self, callback: Callable[[dict], Any]) -> None:
        self._ws.on_broadcast(callback)

    # ── queries ──

    async def list_active(self) -> list[TodoEntity]:
        data = await self._ws.request("todo.list_active")
        return [TodoEntity(**item) for item in data["items"]]

    async def get(self, todo_id: int) -> TodoEntity | None:
        try:
            data = await self._ws.request("todo.get", {"todo_id": todo_id})
            return TodoEntity(**data)
        except ClientError as e:
            if e.is_not_found:
                return None
            raise

    async def get_children(self, todo_id: int) -> list[TodoEntity]:
        data = await self._ws.request("todo.get_children", {"todo_id": todo_id})
        return [TodoEntity(**item) for item in data["items"]]

    async def get_descendants(self, todo_id: int) -> list[TodoEntity]:
        data = await self._ws.request("todo.get_descendants", {"todo_id": todo_id})
        return [TodoEntity(**item) for item in data["items"]]

    async def has_children(self, todo_id: int) -> bool:
        data = await self._ws.request("todo.has_children", {"todo_id": todo_id})
        return data["has_children"]

    # ── mutations ──

    async def add(self, text: str, parent_id: int | None = None, desc: str | None = None) -> TodoEntity:
        data = await self._ws.request("todo.add", {
            "text": text, "parent_id": parent_id, "desc": desc,
        })
        return TodoEntity(**data)

    async def update_text(self, todo_id: int, new_text: str) -> bool:
        data = await self._ws.request("todo.update_text", {
            "todo_id": todo_id, "text": new_text,
        })
        return data["success"]

    async def update_desc(self, todo_id: int, new_desc: str) -> bool:
        data = await self._ws.request("todo.update_desc", {
            "todo_id": todo_id, "desc": new_desc,
        })
        return data["success"]

    async def toggle(self, todo_id: int) -> bool:
        data = await self._ws.request("todo.toggle", {"todo_id": todo_id})
        return data["success"]

    async def toggle_pin(self, todo_id: int) -> bool:
        data = await self._ws.request("todo.toggle_pin", {"todo_id": todo_id})
        return data["success"]

    async def delete(self, todo_id: int) -> int:
        data = await self._ws.request("todo.delete", {"todo_id": todo_id})
        return data["count"]

    async def get_audit(self, limit: int = 50, action: str | None = None) -> list[dict]:
        data = await self._ws.request("todo.get_audit", {
            "limit": limit, "action": action,
        })
        return data["items"]
