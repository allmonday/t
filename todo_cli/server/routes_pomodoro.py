"""Pomodoro REST endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..store import PomodoroStore
from .auth import verify_token
from .schemas import PomodoroSessionCreateRequest, PomodoroSessionListResponse

router = APIRouter(dependencies=[Depends(verify_token)])


def _get_store(request: Request) -> PomodoroStore:
    return PomodoroStore(request.app.state.session_factory)


@router.post("/pomodoro/sessions", status_code=201)
async def record_session(body: PomodoroSessionCreateRequest, request: Request):
    store = _get_store(request)
    return await store.record_session(
        started_at=body.started_at,
        finished_at=body.finished_at,
        phase=body.phase,
        duration_seconds=body.duration_seconds,
        completed=body.completed,
    )


@router.get("/pomodoro/sessions/today", response_model=PomodoroSessionListResponse)
async def today_sessions(request: Request):
    store = _get_store(request)
    items = await store.today_sessions()
    return PomodoroSessionListResponse(items=items)
