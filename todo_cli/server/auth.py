"""Simple Bearer token authentication."""
from __future__ import annotations

from fastapi import Request, WebSocket


def get_api_token(request_or_ws: Request | WebSocket) -> str | None:
    """Get the API token from app state."""
    return getattr(request_or_ws.app.state, "api_token", None)
