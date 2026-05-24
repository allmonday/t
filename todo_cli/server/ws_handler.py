"""WebSocket endpoint handler and message router."""
from __future__ import annotations

import json
import logging
import uuid
from importlib.metadata import version as pkg_version
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

from ..store import PomodoroStore, TodoStore
from .auth import get_api_token
from .connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# ── handler registry ──

_HANDLERS: dict[str, Callable] = {}

MUTATION_TYPES = frozenset({
    "todo.add", "todo.update_text", "todo.update_desc",
    "todo.toggle", "todo.toggle_pin", "todo.delete",
})


def _handler(msg_type: str):
    """Decorator to register a message handler."""
    def decorator(fn):
        _HANDLERS[msg_type] = fn
        return fn
    return decorator


# ── server handlers ──

@_handler("server.info")
async def _server_info(store, data: dict) -> dict:
    return {"version": pkg_version("todoium")}


# ── todo handlers ──

@_handler("todo.list_active")
async def _list_active(store: TodoStore, data: dict) -> dict:
    items = await store.list_active()
    return {"items": [item.model_dump() for item in items]}


@_handler("todo.get")
async def _get(store: TodoStore, data: dict) -> dict:
    todo = await store.get(data["todo_id"])
    if not todo:
        raise _NotFoundError("Todo not found")
    return todo.model_dump()


@_handler("todo.get_children")
async def _get_children(store: TodoStore, data: dict) -> dict:
    items = await store.get_children(data["todo_id"])
    return {"items": [item.model_dump() for item in items]}


@_handler("todo.get_descendants")
async def _get_descendants(store: TodoStore, data: dict) -> dict:
    items = await store.get_descendants(data["todo_id"])
    return {"items": [item.model_dump() for item in items]}


@_handler("todo.has_children")
async def _has_children(store: TodoStore, data: dict) -> dict:
    result = await store.has_children(data["todo_id"])
    return {"has_children": result}


@_handler("todo.add")
async def _add(store: TodoStore, data: dict) -> dict:
    todo = await store.add(
        data["text"],
        data.get("parent_id"),
        data.get("desc"),
    )
    return todo.model_dump()


@_handler("todo.update_text")
async def _update_text(store: TodoStore, data: dict) -> dict:
    success = await store.update_text(data["todo_id"], data["text"])
    return {"success": success}


@_handler("todo.update_desc")
async def _update_desc(store: TodoStore, data: dict) -> dict:
    success = await store.update_desc(data["todo_id"], data["desc"])
    return {"success": success}


@_handler("todo.toggle")
async def _toggle(store: TodoStore, data: dict) -> dict:
    success = await store.toggle(data["todo_id"])
    return {"success": success}


@_handler("todo.toggle_pin")
async def _toggle_pin(store: TodoStore, data: dict) -> dict:
    try:
        success = await store.toggle_pin(data["todo_id"])
    except ValueError as e:
        raise _BadRequestError(str(e))
    return {"success": success}


@_handler("todo.delete")
async def _delete(store: TodoStore, data: dict) -> dict:
    count = await store.delete(data["todo_id"])
    return {"count": count}


@_handler("todo.get_audit")
async def _get_audit(store: TodoStore, data: dict) -> dict:
    items = await store.get_audit(
        limit=data.get("limit", 50),
        action=data.get("action"),
    )
    return {"items": items}


# ── pomodoro handlers ──

@_handler("pomodoro.record_session")
async def _record_session(store: PomodoroStore, data: dict) -> dict:
    session = await store.record_session(
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        phase=data["phase"],
        duration_seconds=data["duration_seconds"],
        completed=data["completed"],
    )
    return session.model_dump()


@_handler("pomodoro.today_sessions")
async def _today_sessions(store: PomodoroStore, data: dict) -> dict:
    items = await store.today_sessions()
    return {"items": [item.model_dump() for item in items]}


# ── error helpers ──

class _NotFoundError(Exception):
    pass

class _BadRequestError(Exception):
    pass


# ── main WebSocket endpoint ──

async def websocket_endpoint(
    websocket: WebSocket,
    manager: ConnectionManager,
    session_factory,
    token: str | None = None,
) -> None:
    """Handle a single WebSocket connection."""
    # auth
    expected = get_api_token()
    if expected is not None and token != expected:
        await websocket.close(code=4001, reason="Invalid token")
        return

    conn_id = uuid.uuid4().hex[:12]
    await manager.connect(conn_id, websocket)
    logger.info("WS client connected: %s", conn_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "response", "req_id": "", "ok": False,
                    "error": "Invalid JSON", "error_code": "invalid_json",
                })
                continue

            req_id = msg.get("req_id", "")
            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            handler = _HANDLERS.get(msg_type)
            if handler is None:
                await websocket.send_json({
                    "type": "response", "req_id": req_id, "ok": False,
                    "error": f"Unknown type: {msg_type}", "error_code": "unknown_type",
                })
                continue

            # dispatch
            store: TodoStore | PomodoroStore
            if msg_type.startswith("pomodoro."):
                store = PomodoroStore(session_factory)
            else:
                store = TodoStore(session_factory)

            try:
                result = await handler(store, data)
                await websocket.send_json({
                    "type": "response", "req_id": req_id, "ok": True, "data": result,
                })
                # broadcast only on successful mutation
                if msg_type in MUTATION_TYPES:
                    await manager.broadcast({
                        "type": "broadcast",
                        "action": "todo.changed",
                        "data": {"mutation": msg_type},
                    }, exclude=conn_id)
            except _NotFoundError:
                await websocket.send_json({
                    "type": "response", "req_id": req_id, "ok": False,
                    "error": "Not found", "error_code": "not_found",
                })
            except _BadRequestError as e:
                await websocket.send_json({
                    "type": "response", "req_id": req_id, "ok": False,
                    "error": str(e), "error_code": "bad_request",
                })
            except (KeyError, TypeError) as e:
                await websocket.send_json({
                    "type": "response", "req_id": req_id, "ok": False,
                    "error": f"Missing or invalid field: {e}", "error_code": "bad_request",
                })
            except Exception:
                logger.exception("Error handling %s", msg_type)
                await websocket.send_json({
                    "type": "response", "req_id": req_id, "ok": False,
                    "error": "Internal error", "error_code": "internal_error",
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS connection error for %s", conn_id)
    finally:
        manager.disconnect(conn_id)
        logger.info("WS client disconnected: %s", conn_id)
