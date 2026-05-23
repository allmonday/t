"""WebSocket connection manager for broadcasting changes to clients."""
from __future__ import annotations

import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks active WebSocket connections and supports broadcast."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, conn_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[conn_id] = websocket

    def disconnect(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)

    async def broadcast(self, message: dict, exclude: str | None = None) -> None:
        """Send message to all connected clients except excluded one."""
        disconnected: list[str] = []
        for conn_id, ws in list(self._connections.items()):
            if conn_id == exclude:
                continue
            try:
                from fastapi.encoders import jsonable_encoder
                import json
                await ws.send_json(message)
            except Exception:
                logger.debug("Failed to send to %s, marking disconnected", conn_id)
                disconnected.append(conn_id)
        for conn_id in disconnected:
            self._connections.pop(conn_id, None)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
