"""Simple Bearer token authentication."""
from __future__ import annotations

_API_TOKEN: str | None = None


def set_api_token(token: str | None) -> None:
    global _API_TOKEN
    _API_TOKEN = token


def get_api_token() -> str | None:
    return _API_TOKEN
