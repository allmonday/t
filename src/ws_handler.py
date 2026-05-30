"""WebSocket endpoint handler — bridges TUI client protocol with nexusx service methods."""
from __future__ import annotations

import json
import logging
import uuid
from importlib.metadata import version as pkg_version
from typing import Callable

from fastapi import WebSocket, WebSocketDisconnect

from src.connection_manager import ConnectionManager
from src.models import Audit, PomodoroSession, Todo
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

logger = logging.getLogger(__name__)


# ── field mapping (new SQLModel → old TodoEntity format) ────────────────


def _todo_to_dict(todo: Todo) -> dict:
    return {
        "id": todo.id,
        "text": todo.text,
        "desc": todo.desc,
        "done": todo.done,
        "parent": todo.parent_id,
        "pinned": todo.pinned,
        "created": todo.created,
        "done_at": todo.done_at,
        "deleted_at": todo.deleted_at,
    }


def _session_to_dict(s: PomodoroSession) -> dict:
    return {
        "id": s.id,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
        "phase": s.phase,
        "duration_seconds": s.duration_seconds,
        "completed": s.completed,
    }


def _audit_to_dict(a: Audit) -> dict:
    return {
        "id": a.id,
        "timestamp": a.timestamp,
        "action": a.action,
        "todo_id": a.todo_id,
        "details": a.details,
    }


# ── handler registry ────────────────────────────────────────────────────

_HANDLERS: dict[str, Callable] = {}

MUTATION_TYPES = frozenset({
    "todo.add", "todo.update_text", "todo.update_desc",
    "todo.toggle", "todo.toggle_pin", "todo.delete",
})


def _handler(msg_type: str):
    def decorator(fn):
        _HANDLERS[msg_type] = fn
        return fn
    return decorator


# ── server handlers ─────────────────────────────────────────────────────


@_handler("server.info")
async def _server_info(data: dict) -> dict:
    return {"version": pkg_version("todoium")}


# ── todo handlers ───────────────────────────────────────────────────────


@_handler("todo.list_active")
async def _list_active(data: dict) -> dict:
    todos = await list_todos()
    return {"items": [_todo_to_dict(t) for t in todos]}


@_handler("todo.get")
async def _get(data: dict) -> dict:
    todo = await get_todo(data["todo_id"])
    if not todo:
        raise _NotFoundError("Todo not found")
    return _todo_to_dict(todo)


@_handler("todo.get_children")
async def _get_children(data: dict) -> dict:
    todos = await get_children(data["todo_id"])
    return {"items": [_todo_to_dict(t) for t in todos]}


@_handler("todo.get_descendants")
async def _get_descendants(data: dict) -> dict:
    todos = await get_descendants(data["todo_id"])
    return {"items": [_todo_to_dict(t) for t in todos]}


@_handler("todo.has_children")
async def _has_children(data: dict) -> dict:
    result = await has_children(data["todo_id"])
    return {"has_children": result}


@_handler("todo.add")
async def _add(data: dict) -> dict:
    todo = await add_todo(
        data["text"],
        data.get("parent_id"),
        data.get("desc"),
    )
    return _todo_to_dict(todo)


@_handler("todo.update_text")
async def _update_text_handler(data: dict) -> dict:
    success = await update_text(data["todo_id"], data["text"])
    return {"success": success}


@_handler("todo.update_desc")
async def _update_desc_handler(data: dict) -> dict:
    success = await update_desc(data["todo_id"], data["desc"])
    return {"success": success}


@_handler("todo.toggle")
async def _toggle(data: dict) -> dict:
    success = await toggle_todo(data["todo_id"])
    return {"success": success}


@_handler("todo.toggle_pin")
async def _toggle_pin(data: dict) -> dict:
    try:
        success = await toggle_pin(data["todo_id"])
    except ValueError as e:
        raise _BadRequestError(str(e))
    return {"success": success}


@_handler("todo.delete")
async def _delete(data: dict) -> dict:
    count = await delete_todo(data["todo_id"])
    return {"count": count}


@_handler("todo.get_audit")
async def _get_audit(data: dict) -> dict:
    audits = await get_audit(
        limit=data.get("limit", 50),
        action=data.get("action"),
    )
    return {"items": [_audit_to_dict(a) for a in audits]}


# ── pomodoro handlers ───────────────────────────────────────────────────


@_handler("pomodoro.record_session")
async def _record_session(data: dict) -> dict:
    session = await record_session(
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        phase=data["phase"],
        duration_seconds=data["duration_seconds"],
        completed=data.get("completed", True),
    )
    return _session_to_dict(session)


@_handler("pomodoro.today_sessions")
async def _today_sessions(data: dict) -> dict:
    sessions = await today_sessions()
    return {"items": [_session_to_dict(s) for s in sessions]}


# ── error helpers ───────────────────────────────────────────────────────


class _NotFoundError(Exception):
    pass


class _BadRequestError(Exception):
    pass


async def _send_error(websocket: WebSocket, req_id: str, error: str, error_code: str) -> None:
    await websocket.send_json({
        "type": "response", "req_id": req_id, "ok": False,
        "error": error, "error_code": error_code,
    })


# ── main WebSocket endpoint ─────────────────────────────────────────────


async def websocket_endpoint(
    websocket: WebSocket,
    manager: ConnectionManager,
    token: str | None = None,
) -> None:
    """Handle a single WebSocket connection."""
    expected = getattr(websocket.app.state, "api_token", None)
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
                await _send_error(websocket, "", "Invalid JSON", "invalid_json")
                continue

            req_id = msg.get("req_id", "")
            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            handler = _HANDLERS.get(msg_type)
            if handler is None:
                await _send_error(websocket, req_id, f"Unknown type: {msg_type}", "unknown_type")
                continue

            try:
                result = await handler(data)
                await websocket.send_json({
                    "type": "response", "req_id": req_id, "ok": True, "data": result,
                })
                if msg_type in MUTATION_TYPES:
                    await manager.broadcast({
                        "type": "broadcast",
                        "action": "todo.changed",
                        "data": {"mutation": msg_type},
                    }, exclude=conn_id)
            except _NotFoundError:
                await _send_error(websocket, req_id, "Not found", "not_found")
            except _BadRequestError as e:
                await _send_error(websocket, req_id, str(e), "bad_request")
            except (KeyError, TypeError) as e:
                await _send_error(websocket, req_id, f"Missing or invalid field: {e}", "bad_request")
            except Exception:
                logger.exception("Error handling %s", msg_type)
                await _send_error(websocket, req_id, "Internal error", "internal_error")

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS connection error for %s", conn_id)
    finally:
        manager.disconnect(conn_id)
        logger.info("WS client disconnected: %s", conn_id)
