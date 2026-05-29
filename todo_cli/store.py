from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import AuditORM, PomodoroSessionEntity, PomodoroSessionORM, TodoEntity, TodoORM


class TodoStore:
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory

    # ── queries ──

    async def list_active(self) -> list[TodoEntity]:
        async with self.session_factory() as session:
            stmt = (
                select(TodoORM)
                .where(TodoORM.deleted_at.is_(None))
                .order_by(TodoORM.pinned.desc(), TodoORM.id)
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
                stmt = stmt.where(TodoORM.done == filter_done)
            stmt = stmt.order_by(TodoORM.pinned.desc(), TodoORM.id)
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
            return [TodoEntity.model_validate(r) for r in result.fetchall()]

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
            orm = TodoORM(text=text, desc=desc, done=False, parent=parent_id, created=now)
            session.add(orm)
            await session.flush()
            await self._log_audit(session, "add", orm.id, {"text": text, "parent": parent_id})
            await self._bubble_up(session, orm.id)
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
            new_done = not row.done
            now = datetime.now().isoformat() if new_done else None
            row.done = new_done
            row.done_at = now
            await self._log_audit(session, "toggle", todo_id, {"done": new_done})
            await session.flush()
            await self._bubble_up(session, todo_id)
            await session.commit()
            return True

    async def toggle_pin(self, todo_id: int) -> bool:
        async with self.session_factory() as session:
            row = await session.get(TodoORM, todo_id)
            if not row or row.deleted_at is not None:
                return False
            if row.parent is not None:
                raise ValueError("Only root todos can be pinned")
            row.pinned = not row.pinned
            await self._log_audit(session, "toggle_pin", todo_id, {"pinned": row.pinned})
            await session.commit()
            return True

    async def delete(self, todo_id: int) -> int:
        async with self.session_factory() as session:
            row = await session.get(TodoORM, todo_id)
            if not row or row.deleted_at is not None:
                return 0
            now = datetime.now().isoformat()
            # 递归 CTE 获取所有子孙节点
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
            await session.execute(
                update(TodoORM)
                .where(TodoORM.id.in_(ids), TodoORM.deleted_at.is_(None))
                .values(deleted_at=now)
            )
            await self._log_audit(session, "delete", todo_id, {
                "text": row.text,
                "subtasks_count": len(desc_ids),
            })
            await session.commit()
            return len(ids)

    # ── internal ──

    async def _bubble_up(self, session: AsyncSession, todo_id: int) -> None:
        """从当前节点向上冒泡更新祖先 done 状态。

        用一次递归 CTE 查出整条祖先链，再逐层查 children 计算 done 状态，
        替代原来的 O(depth) 轮 × 3 次查询。
        """
        # 1. 查出从当前节点到根的祖先链（不含自身）
        ancestor_result = await session.execute(
            text("""
                WITH RECURSIVE ancestors(id, parent) AS (
                    SELECT id, parent FROM todos WHERE id = (
                        SELECT parent FROM todos WHERE id = :tid AND parent IS NOT NULL
                    )
                    UNION ALL
                    SELECT t.id, t.parent FROM todos t
                    INNER JOIN ancestors a ON t.id = a.parent
                )
                SELECT id FROM ancestors ORDER BY id
            """),
            {"tid": todo_id},
        )
        ancestor_ids = [r.id for r in ancestor_result.fetchall()]
        if not ancestor_ids:
            return

        # 2. 一次查出所有祖先的 children
        all_children = (
            await session.scalars(
                select(TodoORM).where(
                    TodoORM.parent.in_(ancestor_ids),
                    TodoORM.deleted_at.is_(None),
                )
            )
        ).all()
        children_by_parent: dict[int, list[TodoORM]] = {}
        for c in all_children:
            children_by_parent.setdefault(c.parent, []).append(c)

        # 3. 从最深祖先向根逐层计算 done 状态
        # ancestors CTE 返回顺序是从叶子到根方向，reverse 后从根到叶子
        for aid in reversed(ancestor_ids):
            siblings = children_by_parent.get(aid, [])
            if not siblings:
                continue
            all_done = all(c.done for c in siblings)
            ancestor = await session.get(TodoORM, aid)
            if not ancestor or ancestor.done == all_done:
                continue
            now = datetime.now().isoformat() if all_done else None
            ancestor.done = all_done
            ancestor.done_at = now
            await self._log_audit(session, "auto_toggle", aid, {
                "done": all_done,
                "triggered_by": todo_id,
            })

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


class PomodoroStore:
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory

    async def record_session(
        self,
        started_at: str,
        finished_at: str,
        phase: str,
        duration_seconds: int,
        completed: bool,
    ) -> PomodoroSessionEntity:
        async with self.session_factory() as session:
            orm = PomodoroSessionORM(
                started_at=started_at,
                finished_at=finished_at,
                phase=phase,
                duration_seconds=duration_seconds,
                completed=completed,
            )
            session.add(orm)
            await session.commit()
            await session.refresh(orm)
            return PomodoroSessionEntity.model_validate(orm)

    async def today_sessions(self) -> list[PomodoroSessionEntity]:
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        async with self.session_factory() as session:
            stmt = (
                select(PomodoroSessionORM)
                .where(PomodoroSessionORM.started_at.like(f"{today_prefix}%"))
                .order_by(PomodoroSessionORM.id)
            )
            rows = (await session.scalars(stmt)).all()
            return [PomodoroSessionEntity.model_validate(r) for r in rows]
