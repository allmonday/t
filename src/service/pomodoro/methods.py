"""Pomodoro domain — independent business methods."""
from datetime import datetime

from sqlmodel import select

from src.db import async_session
from src.models import PomodoroSession


async def record_session(
    started_at: str,
    finished_at: str,
    phase: str,
    duration_seconds: int,
    completed: bool = True,
) -> PomodoroSession:
    """记录番茄钟会话。"""
    async with async_session() as session:
        pomo = PomodoroSession(
            started_at=started_at,
            finished_at=finished_at,
            phase=phase,
            duration_seconds=duration_seconds,
            completed=completed,
        )
        session.add(pomo)
        await session.commit()
        await session.refresh(pomo)
        return pomo


async def today_sessions() -> list[PomodoroSession]:
    """查询今日番茄钟会话。"""
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    async with async_session() as session:
        stmt = (
            select(PomodoroSession)
            .where(PomodoroSession.started_at.like(f"{today_prefix}%"))
            .order_by(PomodoroSession.id)
        )
        result = await session.exec(stmt)
        return list(result.all())
