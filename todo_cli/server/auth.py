"""Simple Bearer token authentication."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Header

_API_TOKEN: str | None = None


def set_api_token(token: str | None) -> None:
    global _API_TOKEN
    _API_TOKEN = token


def get_api_token() -> str | None:
    return _API_TOKEN


async def verify_token(authorization: str = Header(default="")) -> None:
    """Dependency: verify Bearer token. Skipped when _API_TOKEN is None."""
    if _API_TOKEN is None:
        return
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization[7:]
    if token != _API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
