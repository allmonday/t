"""Todo UseCaseService — todo management with auto-loaded children."""
from nexusx import UseCaseService, mutation, query
from src.models import Resolver
from src.service.todo.dtos import AuditItem, TodoBrief, TodoItem
from src.service.todo.methods import (
    add_todo as _add_todo,
    delete_todo as _delete_todo,
    get_audit as _get_audit,
    get_children as _get_children,
    get_descendants as _get_descendants,
    get_todo as _get_todo,
    has_children as _has_children,
    list_todos as _list_todos,
    toggle_pin as _toggle_pin,
    toggle_todo as _toggle_todo,
    update_desc as _update_desc,
    update_text as _update_text,
)


class TodoService(UseCaseService):
    """Todo management service."""

    @query
    async def list_todos(cls, filter_done: bool | None = None, hide_stale: bool = False) -> list[TodoBrief]:
        todos = await _list_todos(filter_done=filter_done, hide_stale=hide_stale)
        dtos = [TodoBrief.model_validate(t) for t in todos]
        return await Resolver().resolve(dtos)

    @query
    async def get_todo(cls, todo_id: int) -> TodoItem | None:
        todo = await _get_todo(todo_id)
        if todo is None:
            return None
        dto = TodoItem.model_validate(todo)
        return await Resolver().resolve(dto)

    @query
    async def get_children(cls, todo_id: int) -> list[TodoBrief]:
        todos = await _get_children(todo_id)
        dtos = [TodoBrief.model_validate(t) for t in todos]
        return await Resolver().resolve(dtos)

    @query
    async def get_descendants(cls, todo_id: int) -> list[TodoBrief]:
        todos = await _get_descendants(todo_id)
        dtos = [TodoBrief.model_validate(t) for t in todos]
        return await Resolver().resolve(dtos)

    @query
    async def has_children(cls, todo_id: int) -> bool:
        return await _has_children(todo_id)

    @mutation
    async def add_todo(cls, text: str, parent_id: int | None = None, desc: str | None = None) -> TodoItem:
        todo = await _add_todo(text=text, parent_id=parent_id, desc=desc)
        dto = TodoItem.model_validate(todo)
        return await Resolver().resolve(dto)

    @mutation
    async def update_text(cls, todo_id: int, text: str) -> bool:
        return await _update_text(todo_id, text)

    @mutation
    async def update_desc(cls, todo_id: int, desc: str) -> bool:
        return await _update_desc(todo_id, desc)

    @mutation
    async def toggle_todo(cls, todo_id: int) -> bool:
        return await _toggle_todo(todo_id)

    @mutation
    async def toggle_pin(cls, todo_id: int) -> bool:
        try:
            return await _toggle_pin(todo_id)
        except ValueError:
            return False

    @mutation
    async def delete_todo(cls, todo_id: int) -> int:
        return await _delete_todo(todo_id)

    @query
    async def get_audit(cls, limit: int = 50, action: str | None = None) -> list[AuditItem]:
        audits = await _get_audit(limit=limit, action=action)
        return [AuditItem.model_validate(a) for a in audits]
