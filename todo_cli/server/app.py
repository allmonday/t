"""FastAPI application factory."""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket

from ..db import create_engine_and_session, init_db, seed_if_empty
from .auth import set_api_token
from .connection_manager import ConnectionManager
from .ws_handler import websocket_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = app.state.engine
    await init_db(engine)
    await seed_if_empty(app.state.session_factory)
    yield
    await engine.dispose()


def create_app(
    db_path: str | None = None,
    api_token: str | None = None,
) -> tuple[FastAPI, str]:
    """Create FastAPI instance.

    Args:
        db_path: SQLite database path. None uses default ~/.todo.db.
        api_token: Auth token. None = auto-generate for local mode.

    Returns:
        (app, token) — the FastAPI app and the resolved token string.
    """
    engine, session_factory = create_engine_and_session(db_path)

    token = api_token if api_token else secrets.token_urlsafe(32)
    set_api_token(token)

    app = FastAPI(lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = session_factory

    manager = ConnectionManager()
    app.state.connection_manager = manager

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str | None = Query(default=None)):
        await websocket_endpoint(
            websocket, manager, session_factory, token=token,
        )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app, token
