from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import AuditORM, TodoEntity, TodoORM


class TodoStore:
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory

    # ── queries ──

    async def list_active(self) -> list[TodoEntity]:
        async with self.session_factory() as session:
            stmt = (
                select(TodoORM)
                .where(TodoORM.deleted_at.is_(None))
                .order_by(TodoORM.id)
            )
            rows = (await session.scalars(stmt)).all()
            return [TodoEntity.model_validate(r) for r in rows]

    async def list_roots(self, filter_done: bool | None = None) -> list[TodoEntity]:
        async with self.session_factory() as session:
            stmt = select(TodoORM).where(
                TodoORM.parent.is_(None),
                TodoORM.deleted_at.is_(None),
            )
            if filter_done is not None:
                stmt = stmt.where(TodoORM.done == int(filter_done))
            stmt = stmt.order_by(TodoORM.id)
            rows = (await session.scalars(stmt)).all()
            return [TodoEntity.model_validate(r) for r in rows]

    async def get(self, todo_id: int) -> TodoEntity | None:
        async with self.session_factory() as session:
            row = await session.get(TodoORM, todo_id)
            if row and row.deleted_at is None:
                return TodoEntity.model_validate(row)
            return None

    async def get_children(self, todo_id: int) -> list[TodoEntity]:
        async with self.session_factory() as session:
            stmt = (
                select(TodoORM)
                .where(TodoORM.parent == todo_id, TodoORM.deleted_at.is_(None))
                .order_by(TodoORM.id)
            )
            rows = (await session.scalars(stmt)).all()
            return [TodoEntity.model_validate(r) for r in rows]

    async def get_descendants(self, todo_id: int) -> list[TodoEntity]:
        """递归 CTE 获取所有子孙节点。"""
        async with self.session_factory() as session:
            result = await session.execute(
                text("""
                    WITH RECURSIVE descendants(id) AS (
                        SELECT id FROM todos WHERE parent = :pid AND deleted_at IS NULL
                        UNION ALL
                        SELECT t.id FROM todos t
                        INNER JOIN descendants d ON t.parent = d.id
                        WHERE t.deleted_at IS NULL
                    )
                    SELECT todos.* FROM todos
                    INNER JOIN descendants d ON todos.id = d.id
                    ORDER BY todos.id
                """),
                {"pid": todo_id},
            )
            return [
                TodoEntity(
                    id=r.id,
                    text=r.text,
                    desc=r.desc,
                    done=bool(r.done),
                    parent=r.parent,
                    created=r.created,
                    done_at=r.done_at,
                    deleted_at=r.deleted_at,
                )
                for r in result.fetchall()
            ]

    async def has_children(self, todo_id: int) -> bool:
        async with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(TodoORM)
                .where(TodoORM.parent == todo_id, TodoORM.deleted_at.is_(None))
            )
            count = await session.scalar(stmt)
            return (count or 0) > 0

    # ── mutations ──

    async def add(self, text: str, parent_id: int | None = None, desc: str | None = None) -> TodoEntity:
        async with self.session_factory() as session:
            if parent_id is not None:
                parent = await session.get(TodoORM, parent_id)
                if not parent or parent.deleted_at is not None:
                    raise ValueError(f"Parent todo #{parent_id} not found")
            now = datetime.now().isoformat()
            orm = TodoORM(text=text, desc=desc, done=0, parent=parent_id, created=now)
            session.add(orm)
            await session.flush()
            await self._log_audit(session, "add", orm.id, {"text": text, "parent": parent_id})
            await session.commit()
            return TodoEntity.model_validate(orm)

    async def update_text(self, todo_id: int, new_text: str) -> bool:
        async with self.session_factory() as session:
            row = await session.get(TodoORM, todo_id)
            if not row or row.deleted_at is not None:
                return False
            old_text = row.text
            row.text = new_text
            await self._log_audit(session, "edit", todo_id, {"old_text": old_text, "new_text": new_text})
            await session.commit()
            return True

    async def update_desc(self, todo_id: int, new_desc: str) -> bool:
        async with self.session_factory() as session:
            row = await session.get(TodoORM, todo_id)
            if not row or row.deleted_at is not None:
                return False
            old_desc = row.desc
            row.desc = new_desc
            await self._log_audit(session, "edit_desc", todo_id, {"old_desc": old_desc, "new_desc": new_desc})
            await session.commit()
            return True

    async def toggle(self, todo_id: int) -> bool:
        async with self.session_factory() as session:
            row = await session.get(TodoORM, todo_id)
            if not row or row.deleted_at is not None:
                return False
            child_count = await session.scalar(
                select(func.count())
                .select_from(TodoORM)
                .where(TodoORM.parent == todo_id, TodoORM.deleted_at.is_(None))
            )
            if child_count and child_count > 0:
                return False
            new_done = not bool(row.done)
            now = datetime.now().isoformat() if new_done else None
            row.done = int(new_done)
            row.done_at = now
            await self._log_audit(session, "toggle", todo_id, {"done": new_done})
            await session.flush()
            await self._bubble_up(session, todo_id)
            await session.commit()
            return True

    async def delete(self, todo_id: int) -> int:
        async with self.session_factory() as session:
            row = await session.get(TodoORM, todo_id)
            if not row or row.deleted_at is not None:
                return 0
            now = datetime.now().isoformat()
            # 内联递归 CTE，避免跨 session
            result = await session.execute(
                text("""
                    WITH RECURSIVE descendants(id) AS (
                        SELECT id FROM todos WHERE parent = :pid AND deleted_at IS NULL
                        UNION ALL
                        SELECT t.id FROM todos t
                        INNER JOIN descendants d ON t.parent = d.id
                        WHERE t.deleted_at IS NULL
                    )
                    SELECT id FROM descendants
                """),
                {"pid": todo_id},
            )
            desc_ids = [r.id for r in result.fetchall()]
            ids = [todo_id] + desc_ids
            placeholders = ",".join(f":id_{i}" for i in range(len(ids)))
            params = {f"id_{i}": v for i, v in enumerate(ids)}
            params["now"] = now
            await session.execute(
                text(
                    f"UPDATE todos SET deleted_at = :now "
                    f"WHERE id IN ({placeholders}) AND deleted_at IS NULL"
                ),
                params,
            )
            await self._log_audit(session, "delete", todo_id, {
                "text": row.text,
                "subtasks_count": len(desc_ids),
            })
            await session.commit()
            return len(ids)

    # ── internal ──

    async def _bubble_up(self, session: AsyncSession, todo_id: int) -> None:
        """从当前节点向上冒泡更新祖先 done 状态。"""
        row = await session.get(TodoORM, todo_id)
        if not row or row.parent is None:
            return
        parent = await session.get(TodoORM, row.parent)
        if not parent:
            return
        children = (
            await session.scalars(
                select(TodoORM).where(
                    TodoORM.parent == parent.id,
                    TodoORM.deleted_at.is_(None),
                )
            )
        ).all()
        all_done = len(children) > 0 and all(bool(c.done) for c in children)
        if bool(parent.done) != all_done:
            now = datetime.now().isoformat() if all_done else None
            parent.done = int(all_done)
            parent.done_at = now
            await self._log_audit(session, "auto_toggle", parent.id, {
                "done": all_done,
                "triggered_by": todo_id,
            })
            await self._bubble_up(session, parent.id)

    async def _log_audit(
        self, session: AsyncSession, action: str, todo_id: int, details: dict
    ) -> None:
        entry = AuditORM(
            timestamp=datetime.now().isoformat(),
            action=action,
            todo_id=todo_id,
            details=json.dumps(details, ensure_ascii=False),
        )
        session.add(entry)

    async def get_audit(
        self, limit: int = 50, action: str | None = None
    ) -> list[dict]:
        async with self.session_factory() as session:
            stmt = select(AuditORM).order_by(AuditORM.id.desc()).limit(limit)
            if action:
                stmt = stmt.where(AuditORM.action == action)
            rows = (await session.scalars(stmt)).all()
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "action": r.action,
                    "todo_id": r.todo_id,
                    "details": json.loads(r.details) if r.details else {},
                }
                for r in rows
            ]
