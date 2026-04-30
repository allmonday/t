"""Pomodoro timer state machine — pure logic, no UI or DB dependencies."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Phase(Enum):
    FOCUS = "focus"
    BREAK = "break"
    LONG_BREAK = "long_break"


class TimerState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


PHASE_DURATIONS: dict[Phase, int] = {
    Phase.FOCUS: 25 * 60,
    Phase.BREAK: 5 * 60,
    Phase.LONG_BREAK: 15 * 60,
}

LONG_BREAK_INTERVAL = 2


PHASE_LABELS: dict[Phase, str] = {
    Phase.FOCUS: "FOCUS",
    Phase.BREAK: "BREAK",
    Phase.LONG_BREAK: "LONG BREAK",
}


@dataclass
class PhaseTransition:
    """Returned by tick()/skip() when a phase ends."""

    finished_phase: Phase
    started_at: str
    finished_at: str
    duration_seconds: int
    completed: bool  # True = timer ran out, False = skipped
    next_phase: Phase
    focus_count: int


class PomodoroTimer:
    """Polling-based Pomodoro timer. Call tick() every ~1 second."""

    def __init__(self) -> None:
        self.state: TimerState = TimerState.IDLE
        self.phase: Phase = Phase.FOCUS
        self.focus_count: int = 0
        self.elapsed: float = 0.0
        self._last_tick: float = 0.0
        self._phase_start_iso: str = ""

    @property
    def duration(self) -> int:
        return PHASE_DURATIONS[self.phase]

    @property
    def remaining(self) -> int:
        return max(0, self.duration - int(self.elapsed))

    @property
    def progress(self) -> float:
        if self.duration == 0:
            return 1.0
        return min(1.0, self.elapsed / self.duration)

    @property
    def is_active(self) -> bool:
        return self.state != TimerState.IDLE

    @property
    def display_round(self) -> int:
        if self.phase == Phase.FOCUS:
            return self.focus_count + 1
        return self.focus_count

    def start(self) -> None:
        if self.state != TimerState.IDLE:
            return
        # If phase is already FOCUS with focus_count > 0, we're continuing after a break
        if self.focus_count == 0:
            self.phase = Phase.FOCUS
        self.elapsed = 0.0
        self._last_tick = time.monotonic()
        self._phase_start_iso = datetime.now().isoformat()
        self.state = TimerState.RUNNING

    def pause(self) -> None:
        if self.state == TimerState.RUNNING:
            now = time.monotonic()
            self.elapsed += now - self._last_tick
            self.state = TimerState.PAUSED

    def resume(self) -> None:
        if self.state == TimerState.PAUSED:
            self._last_tick = time.monotonic()
            self.state = TimerState.RUNNING

    def reset(self) -> None:
        self.state = TimerState.IDLE
        self.phase = Phase.FOCUS
        self.focus_count = 0
        self.elapsed = 0.0

    def tick(self) -> PhaseTransition | None:
        if self.state != TimerState.RUNNING:
            return None
        now = time.monotonic()
        self.elapsed += now - self._last_tick
        self._last_tick = now
        if self.elapsed >= self.duration:
            return self._complete_phase(skipped=False)
        return None

    def skip(self) -> PhaseTransition | None:
        if self.state not in (TimerState.RUNNING, TimerState.PAUSED):
            return None
        return self._complete_phase(skipped=True)

    def _complete_phase(self, skipped: bool) -> PhaseTransition:
        finished_phase = self.phase
        finished_start = self._phase_start_iso
        finished_at = datetime.now().isoformat()
        actual_duration = int(self.elapsed)

        if finished_phase == Phase.FOCUS:
            self.focus_count += 1
            if self.focus_count % LONG_BREAK_INTERVAL == 0:
                next_phase = Phase.LONG_BREAK
            else:
                next_phase = Phase.BREAK
        else:
            next_phase = Phase.FOCUS

        self.phase = next_phase
        self.elapsed = 0.0
        self._last_tick = time.monotonic()
        self._phase_start_iso = datetime.now().isoformat()
        # Auto-start breaks, but stop before next focus round
        if next_phase == Phase.FOCUS:
            self.state = TimerState.IDLE
        else:
            self.state = TimerState.RUNNING

        return PhaseTransition(
            finished_phase=finished_phase,
            started_at=finished_start,
            finished_at=finished_at,
            duration_seconds=actual_duration,
            completed=not skipped,
            next_phase=next_phase,
            focus_count=self.focus_count,
        )
