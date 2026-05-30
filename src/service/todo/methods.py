"""Todo domain — independent business methods."""
import json
from datetime import datetime

from sqlmodel import func, select, text, update

from src.db import async_session
from src.models import Audit, Todo


async def list_todos(
    filter_done: bool | None = None,
    hide_stale: bool = False,
) -> list[Todo]:
    """列出所有活跃任务，支持按完成状态过滤。"""
    async with async_session() as session:
        stmt = select(Todo).where(Todo.deleted_at.is_(None))
        if filter_done is not None:
            stmt = stmt.where(Todo.done == filter_done)
        if hide_stale:
            cutoff = datetime.now().isoformat()
            stmt = stmt.where(
                text("(done = 1 AND done_at > ?) OR done = 0").bindparams(
                    cutoff
                )
            )
        stmt = stmt.order_by(Todo.pinned.desc(), Todo.id)
        result = await session.exec(stmt)
        return list(result.all())


async def get_todo(todo_id: int) -> Todo | None:
    """获取单个任务，已删除返回 None。"""
    async with async_session() as session:
        row = await session.get(Todo, todo_id)
        if row and row.deleted_at is None:
            return row
        return None


async def get_children(todo_id: int) -> list[Todo]:
    """获取直接子任务。"""
    async with async_session() as session:
        stmt = (
            select(Todo)
            .where(Todo.parent_id == todo_id, Todo.deleted_at.is_(None))
            .order_by(Todo.id)
        )
        result = await session.exec(stmt)
        return list(result.all())


async def get_descendants(todo_id: int) -> list[Todo]:
    """递归 CTE 获取所有子孙节点。"""
    async with async_session() as session:
        result = await session.execute(
            text("""
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM todo WHERE parent_id = :pid AND deleted_at IS NULL
                    UNION ALL
                    SELECT t.id FROM todo t
                    INNER JOIN descendants d ON t.parent_id = d.id
                    WHERE t.deleted_at IS NULL
                )
                SELECT todo.* FROM todo
                INNER JOIN descendants d ON todo.id = d.id
                ORDER BY todo.id
            """),
            {"pid": todo_id},
        )
        return [Todo.model_validate(r) for r in result.fetchall()]


async def has_children(todo_id: int) -> bool:
    """是否有子任务。"""
    async with async_session() as session:
        stmt = (
            select(func.count())
            .select_from(Todo)
            .where(Todo.parent_id == todo_id, Todo.deleted_at.is_(None))
        )
        count = await session.scalar(stmt)
        return (count or 0) > 0


async def add_todo(
    text: str,
    parent_id: int | None = None,
    desc: str | None = None,
) -> Todo:
    """添加任务，支持指定父任务。"""
    async with async_session() as session:
        now = datetime.now().isoformat()
        todo = Todo(text=text, desc=desc, parent_id=parent_id, created=now)
        session.add(todo)
        await session.commit()
        await session.refresh(todo)
        await _log_audit(session, "add", todo.id, {"text": text, "parent_id": parent_id})
        await session.commit()
        return todo


async def update_text(todo_id: int, new_text: str) -> bool:
    """修改任务标题。"""
    async with async_session() as session:
        row = await session.get(Todo, todo_id)
        if not row or row.deleted_at is not None:
            return False
        old_text = row.text
        row.text = new_text
        await _log_audit(session, "edit", todo_id, {"old_text": old_text, "new_text": new_text})
        await session.commit()
        return True


async def update_desc(todo_id: int, new_desc: str) -> bool:
    """修改任务描述。"""
    async with async_session() as session:
        row = await session.get(Todo, todo_id)
        if not row or row.deleted_at is not None:
            return False
        old_desc = row.desc
        row.desc = new_desc
        await _log_audit(session, "edit_desc", todo_id, {"old_desc": old_desc, "new_desc": new_desc})
        await session.commit()
        return True


async def toggle_todo(todo_id: int) -> bool:
    """切换任务完成状态（仅叶子节点）。"""
    async with async_session() as session:
        row = await session.get(Todo, todo_id)
        if not row or row.deleted_at is not None:
            return False
        child_count = await session.scalar(
            select(func.count())
            .select_from(Todo)
            .where(Todo.parent_id == todo_id, Todo.deleted_at.is_(None))
        )
        if child_count and child_count > 0:
            return False
        new_done = not row.done
        row.done = new_done
        row.done_at = datetime.now().isoformat() if new_done else None
        await _log_audit(session, "toggle", todo_id, {"done": new_done})
        await session.commit()
        return True


async def toggle_pin(todo_id: int) -> bool:
    """切换置顶（仅根节点）。"""
    async with async_session() as session:
        row = await session.get(Todo, todo_id)
        if not row or row.deleted_at is not None:
            return False
        if row.parent_id is not None:
            raise ValueError("Only root todos can be pinned")
        row.pinned = not row.pinned
        await _log_audit(session, "toggle_pin", todo_id, {"pinned": row.pinned})
        await session.commit()
        return True


async def delete_todo(todo_id: int) -> int:
    """软删除任务及其所有子孙。返回删除数量。"""
    async with async_session() as session:
        row = await session.get(Todo, todo_id)
        if not row or row.deleted_at is not None:
            return 0
        now = datetime.now().isoformat()
        result = await session.execute(
            text("""
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM todo WHERE parent_id = :pid AND deleted_at IS NULL
                    UNION ALL
                    SELECT t.id FROM todo t
                    INNER JOIN descendants d ON t.parent_id = d.id
                    WHERE t.deleted_at IS NULL
                )
                SELECT id FROM descendants
            """),
            {"pid": todo_id},
        )
        desc_ids = [r.id for r in result.fetchall()]
        ids = [todo_id] + desc_ids
        await session.execute(
            update(Todo)
            .where(Todo.id.in_(ids), Todo.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        await _log_audit(session, "delete", todo_id, {
            "text": row.text,
            "subtasks_count": len(desc_ids),
        })
        await session.commit()
        return len(ids)


async def get_audit(limit: int = 50, action: str | None = None) -> list[Audit]:
    """查询审计记录。"""
    async with async_session() as session:
        stmt = select(Audit).order_by(Audit.id.desc()).limit(limit)
        if action:
            stmt = stmt.where(Audit.action == action)
        result = await session.exec(stmt)
        return list(result.all())


async def _log_audit(session, action: str, todo_id: int, details: dict) -> None:
    entry = Audit(
        timestamp=datetime.now().isoformat(),
        action=action,
        todo_id=todo_id,
        details=json.dumps(details, ensure_ascii=False),
    )
    session.add(entry)
