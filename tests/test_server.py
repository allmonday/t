"""Server endpoint tests using httpx AsyncClient + ASGITransport."""
from __future__ import annotations

import pytest
import httpx

from todo_cli.models import Base
from todo_cli.server.app import create_app


@pytest.fixture
async def client():
    app, token = create_app(db_path=":memory:")
    # Create tables manually for :memory: (skip alembic)
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        yield c
    await app.state.engine.dispose()


# ── health ──


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── todo CRUD ──


@pytest.mark.asyncio
async def test_add_and_list(client):
    r = await client.post("/api/todos", json={"text": "hello"})
    assert r.status_code == 201
    todo = r.json()
    assert todo["text"] == "hello"
    assert todo["id"] is not None

    r = await client.get("/api/todos")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_add_with_parent(client):
    r = await client.post("/api/todos", json={"text": "parent"})
    parent_id = r.json()["id"]
    r = await client.post("/api/todos", json={"text": "child", "parent_id": parent_id})
    assert r.status_code == 201
    assert r.json()["parent"] == parent_id


@pytest.mark.asyncio
async def test_add_invalid_parent(client):
    r = await client.post("/api/todos", json={"text": "x", "parent_id": 9999})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_todo(client):
    r = await client.post("/api/todos", json={"text": "test"})
    todo_id = r.json()["id"]
    r = await client.get(f"/api/todos/{todo_id}")
    assert r.status_code == 200
    assert r.json()["text"] == "test"


@pytest.mark.asyncio
async def test_get_todo_not_found(client):
    r = await client.get("/api/todos/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_text(client):
    r = await client.post("/api/todos", json={"text": "old"})
    todo_id = r.json()["id"]
    r = await client.put(f"/api/todos/{todo_id}/text", json={"text": "new"})
    assert r.status_code == 200
    assert r.json()["success"] is True
    r = await client.get(f"/api/todos/{todo_id}")
    assert r.json()["text"] == "new"


@pytest.mark.asyncio
async def test_update_desc(client):
    r = await client.post("/api/todos", json={"text": "t"})
    todo_id = r.json()["id"]
    r = await client.put(f"/api/todos/{todo_id}/desc", json={"desc": "my desc"})
    assert r.status_code == 200
    assert r.json()["success"] is True
    r = await client.get(f"/api/todos/{todo_id}")
    assert r.json()["desc"] == "my desc"


@pytest.mark.asyncio
async def test_toggle(client):
    r = await client.post("/api/todos", json={"text": "t"})
    todo_id = r.json()["id"]
    r = await client.put(f"/api/todos/{todo_id}/toggle")
    assert r.status_code == 200
    assert r.json()["success"] is True
    r = await client.get(f"/api/todos/{todo_id}")
    assert r.json()["done"] is True


@pytest.mark.asyncio
async def test_toggle_parent_fails(client):
    r = await client.post("/api/todos", json={"text": "parent"})
    pid = r.json()["id"]
    await client.post("/api/todos", json={"text": "child", "parent_id": pid})
    r = await client.put(f"/api/todos/{pid}/toggle")
    assert r.json()["success"] is False


@pytest.mark.asyncio
async def test_has_children(client):
    r = await client.post("/api/todos", json={"text": "parent"})
    pid = r.json()["id"]
    r = await client.get(f"/api/todos/{pid}/has-children")
    assert r.json()["has_children"] is False
    await client.post("/api/todos", json={"text": "child", "parent_id": pid})
    r = await client.get(f"/api/todos/{pid}/has-children")
    assert r.json()["has_children"] is True


@pytest.mark.asyncio
async def test_get_children(client):
    r = await client.post("/api/todos", json={"text": "parent"})
    pid = r.json()["id"]
    await client.post("/api/todos", json={"text": "c1", "parent_id": pid})
    await client.post("/api/todos", json={"text": "c2", "parent_id": pid})
    r = await client.get(f"/api/todos/{pid}/children")
    assert len(r.json()["items"]) == 2


@pytest.mark.asyncio
async def test_get_descendants(client):
    r = await client.post("/api/todos", json={"text": "root"})
    rid = r.json()["id"]
    r = await client.post("/api/todos", json={"text": "c1", "parent_id": rid})
    c1_id = r.json()["id"]
    await client.post("/api/todos", json={"text": "c1a", "parent_id": c1_id})
    r = await client.get(f"/api/todos/{rid}/descendants")
    assert len(r.json()["items"]) == 2


@pytest.mark.asyncio
async def test_delete(client):
    r = await client.post("/api/todos", json={"text": "to-delete"})
    todo_id = r.json()["id"]
    r = await client.delete(f"/api/todos/{todo_id}")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    r = await client.get(f"/api/todos/{todo_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_with_children(client):
    r = await client.post("/api/todos", json={"text": "parent"})
    pid = r.json()["id"]
    await client.post("/api/todos", json={"text": "child", "parent_id": pid})
    r = await client.delete(f"/api/todos/{pid}")
    assert r.json()["count"] == 2


# ── auth ──


@pytest.mark.asyncio
async def test_auth_required():
    app, token = create_app(db_path=":memory:")
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # No auth header
        r = await c.get("/api/todos")
        assert r.status_code == 401
        # Wrong token
        r = await c.get("/api/todos", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401
        # Correct token
        r = await c.get("/api/todos", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
    await app.state.engine.dispose()


# ── pomodoro ──


@pytest.mark.asyncio
async def test_pomodoro_session(client):
    from datetime import datetime

    now = datetime.now().isoformat()
    r = await client.post("/api/pomodoro/sessions", json={
        "started_at": now,
        "finished_at": now,
        "phase": "focus",
        "duration_seconds": 1500,
        "completed": True,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["phase"] == "focus"
    assert data["completed"] is True


@pytest.mark.asyncio
async def test_pomodoro_today_sessions(client):
    r = await client.get("/api/pomodoro/sessions/today")
    assert r.status_code == 200
    assert "items" in r.json()
