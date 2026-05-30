"""Database seed data.

Phase 1: create_all + mock seed (供团队讨论数据样本).
"""
from datetime import datetime

from sqlmodel import SQLModel, select

from src.db import async_session, engine
from src.models import Audit, PomodoroSession, Todo


async def init_db() -> None:
    """Create tables and seed mock data."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with async_session() as session:
        existing = await session.exec(select(Todo))
        if existing.first():
            return

        now = datetime.now().isoformat()

        # Root todos
        root1 = Todo(text="快速上手 Todo CLI", created=now)
        root2 = Todo(text="示例项目", created=now)
        root3 = Todo(text="按 d 删除此任务试试", created=now)
        for t in [root1, root2, root3]:
            session.add(t)
        await session.commit()
        for t in [root1, root2, root3]:
            await session.refresh(t)

        # Children under root1
        c1 = Todo(text="按 Space 切换完成状态", parent_id=root1.id, created=now)
        c2 = Todo(text="按 Tab 添加子任务", parent_id=root1.id, created=now)
        c3 = Todo(text="按 ←→ 折叠/展开树节点", parent_id=root1.id, created=now)
        for t in [c1, c2, c3]:
            session.add(t)
        await session.commit()

        # Children under root2 — one done
        c4 = Todo(text="设计方案", parent_id=root2.id, done=True, created=now, done_at=now)
        c5 = Todo(text="编码实现", parent_id=root2.id, created=now)
        for t in [c4, c5]:
            session.add(t)
        await session.commit()

        # Grandchild under c5
        gc1 = Todo(text="编写单元测试", parent_id=c5.id, created=now)
        gc2 = Todo(text="集成测试", parent_id=c5.id, created=now)
        for t in [gc1, gc2]:
            session.add(t)
        await session.commit()

        # Pinned root
        root2.pinned = True
        session.add(root2)
        await session.commit()

        # Audit records
        audit_entries = [
            Audit(timestamp=now, action="add", todo_id=root1.id, details='{"text": "快速上手 Todo CLI"}'),
            Audit(timestamp=now, action="add", todo_id=root2.id, details='{"text": "示例项目"}'),
            Audit(timestamp=now, action="toggle", todo_id=c4.id, details='{"done": true}'),
            Audit(timestamp=now, action="toggle_pin", todo_id=root2.id, details='{"pinned": true}'),
        ]
        for a in audit_entries:
            session.add(a)
        await session.commit()

        # Pomodoro sessions
        pomo_entries = [
            PomodoroSession(
                started_at=now, finished_at=now,
                phase="focus", duration_seconds=1500, completed=True,
            ),
            PomodoroSession(
                started_at=now, finished_at=now,
                phase="break", duration_seconds=300, completed=True,
            ),
            PomodoroSession(
                started_at=now, finished_at=now,
                phase="focus", duration_seconds=900, completed=False,
            ),
        ]
        for p in pomo_entries:
            session.add(p)
        await session.commit()
