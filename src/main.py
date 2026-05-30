"""FastAPI application entry point.

Phase 1: Voyager (ER diagram)
Phase 2: + GraphQL
Phase 3: + REST + MCP
Phase 4: + WebSocket (TUI transport)
"""
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from src.database import init_db
from src.db import async_session
from src.models import BaseEntity, er, mount_method  # noqa: E402
from src.service.pomodoro.service import PomodoroService  # noqa: E402
from src.service.todo.service import TodoService  # noqa: E402

# ── Mount methods onto entities (must be called before GraphQL handler) ──

mount_method()

# ── GraphQL handler (must be created AFTER mount_method) ──────────────

from nexusx import GraphQLHandler  # noqa: E402

graphql_handler = GraphQLHandler(
    base=BaseEntity,
    session_factory=async_session,
)

# ── MCP (must be created before lifespan) ─────────────────────────────

from nexusx import UseCaseAppConfig, create_flat_mcp_server  # noqa: E402

app_config = UseCaseAppConfig(
    name="todoium",
    services=[TodoService, PomodoroService],
    description="Todoium task & pomodoro management",
)

mcp = create_flat_mcp_server(apps=[app_config], name="Todoium MCP")
mcp_http = mcp.http_app(path="/", transport="streamable-http", stateless_http=True)


# ── FastAPI app ───────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print(f"Todoium server started. Token: {app.state.api_token}")
    async with mcp_http.lifespan(mcp_http):
        yield


app = FastAPI(
    title="Todoium",
    version="0.1.0",
    lifespan=lifespan,
)

# Auth token for WebSocket connections
_token = os.environ.get("TODOIUM_TOKEN") or secrets.token_urlsafe(32)
app.state.api_token = _token

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Voyager visualization ─────────────────────────────────────────────

from nexusx import create_use_case_voyager  # noqa: E402

voyager_app = create_use_case_voyager(
    services=[TodoService, PomodoroService],
    er_manager=er,
    name="Todoium API",
)
app.mount("/voyager", voyager_app)


# ── GraphQL endpoints ────────────────────────────────────────────────


class GraphQLRequest(BaseModel):
    query: str
    variables: dict[str, Any] | None = None
    operation_name: str | None = None


@app.get("/graphql", response_class=HTMLResponse)
async def graphiql():
    return graphql_handler.get_graphiql_html()


@app.post("/graphql")
async def graphql_endpoint(req: GraphQLRequest):
    return await graphql_handler.execute(
        query=req.query,
        variables=req.variables,
        operation_name=req.operation_name,
    )


@app.get("/schema", response_class=PlainTextResponse)
async def graphql_schema():
    return graphql_handler.get_sdl()


# ── REST router ──────────────────────────────────────────────────────

from nexusx import create_use_case_router  # noqa: E402

app.include_router(create_use_case_router(app_config))


# ── MCP mount ────────────────────────────────────────────────────────

app.mount("/mcp", mcp_http)


# ── WebSocket (TUI transport) ────────────────────────────────────────

from src.connection_manager import ConnectionManager  # noqa: E402
from src.ws_handler import websocket_endpoint  # noqa: E402

_manager = ConnectionManager()


@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str | None = Query(default=None)):
    await websocket_endpoint(websocket, _manager, token=token)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
