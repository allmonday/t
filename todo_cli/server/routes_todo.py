"""Todo REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..store import TodoStore
from .auth import verify_token
from .schemas import (
    AuditListResponse,
    DescendantsResponse,
    HasChildrenResponse,
    TodoCreateRequest,
    TodoDeleteResponse,
    TodoListResponse,
    TodoToggleResponse,
    TodoUpdateDescRequest,
    TodoUpdateTextRequest,
)

router = APIRouter(dependencies=[Depends(verify_token)])


def _get_store(request: Request) -> TodoStore:
    return TodoStore(request.app.state.session_factory)


@router.get("/todos", response_model=TodoListResponse)
async def list_todos(request: Request):
    store = _get_store(request)
    items = await store.list_active()
    return TodoListResponse(items=items)


@router.get("/todos/{todo_id}")
async def get_todo(todo_id: int, request: Request):
    store = _get_store(request)
    todo = await store.get(todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.get("/todos/{todo_id}/children", response_model=TodoListResponse)
async def get_children(todo_id: int, request: Request):
    store = _get_store(request)
    items = await store.get_children(todo_id)
    return TodoListResponse(items=items)


@router.get("/todos/{todo_id}/descendants", response_model=DescendantsResponse)
async def get_descendants(todo_id: int, request: Request):
    store = _get_store(request)
    items = await store.get_descendants(todo_id)
    return DescendantsResponse(items=items)


@router.get("/todos/{todo_id}/has-children", response_model=HasChildrenResponse)
async def has_children(todo_id: int, request: Request):
    store = _get_store(request)
    result = await store.has_children(todo_id)
    return HasChildrenResponse(has_children=result)


@router.post("/todos", status_code=201)
async def create_todo(body: TodoCreateRequest, request: Request):
    store = _get_store(request)
    try:
        return await store.add(body.text, body.parent_id, body.desc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/todos/{todo_id}/text", response_model=TodoToggleResponse)
async def update_text(todo_id: int, body: TodoUpdateTextRequest, request: Request):
    store = _get_store(request)
    success = await store.update_text(todo_id, body.text)
    return TodoToggleResponse(success=success)


@router.put("/todos/{todo_id}/desc", response_model=TodoToggleResponse)
async def update_desc(todo_id: int, body: TodoUpdateDescRequest, request: Request):
    store = _get_store(request)
    success = await store.update_desc(todo_id, body.desc)
    return TodoToggleResponse(success=success)


@router.put("/todos/{todo_id}/toggle", response_model=TodoToggleResponse)
async def toggle_todo(todo_id: int, request: Request):
    store = _get_store(request)
    success = await store.toggle(todo_id)
    return TodoToggleResponse(success=success)


@router.delete("/todos/{todo_id}", response_model=TodoDeleteResponse)
async def delete_todo(todo_id: int, request: Request):
    store = _get_store(request)
    count = await store.delete(todo_id)
    return TodoDeleteResponse(count=count)


@router.get("/audit", response_model=AuditListResponse)
async def get_audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    action: str | None = Query(default=None),
):
    store = _get_store(request)
    items = await store.get_audit(limit=limit, action=action)
    return AuditListResponse(items=items)
