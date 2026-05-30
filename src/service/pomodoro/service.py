"""Pomodoro UseCaseService — session recording and querying."""
from nexusx import UseCaseService, mutation, query
from src.service.pomodoro.dtos import PomodoroSessionItem
from src.service.pomodoro.methods import (
    record_session as _record_session,
    today_sessions as _today_sessions,
)


class PomodoroService(UseCaseService):
    """Pomodoro session management service."""

    @query
    async def today_sessions(cls) -> list[PomodoroSessionItem]:
        sessions = await _today_sessions()
        return [PomodoroSessionItem.model_validate(s) for s in sessions]

    @mutation
    async def record_session(
        cls,
        started_at: str,
        finished_at: str,
        phase: str,
        duration_seconds: int,
        completed: bool = True,
    ) -> PomodoroSessionItem:
        session = await _record_session(
            started_at=started_at,
            finished_at=finished_at,
            phase=phase,
            duration_seconds=duration_seconds,
            completed=completed,
        )
        return PomodoroSessionItem.model_validate(session)
