"""Tests for the Pomodoro timer state machine."""

from __future__ import annotations

import time

from todo_cli.pomodoro import (
    LONG_BREAK_INTERVAL,
    PHASE_DURATIONS,
    Phase,
    PomodoroTimer,
    TimerState,
)


def test_initial_state_is_idle():
    t = PomodoroTimer()
    assert t.state == TimerState.IDLE
    assert t.phase == Phase.FOCUS
    assert t.focus_count == 0
    assert t.elapsed == 0.0
    assert not t.is_active


def test_start_sets_running_focus():
    t = PomodoroTimer()
    t.start()
    assert t.state == TimerState.RUNNING
    assert t.phase == Phase.FOCUS
    assert t.is_active
    assert t.display_round == 1


def test_start_when_already_running_is_noop():
    t = PomodoroTimer()
    t.start()
    t.elapsed = 100.0
    t.start()  # should not reset
    assert t.elapsed == 100.0


def test_tick_decrements_remaining():
    t = PomodoroTimer()
    t.start()
    # Simulate 10 seconds passing
    t._last_tick = time.monotonic() - 10
    t.tick()
    assert t.remaining <= PHASE_DURATIONS[Phase.FOCUS] - 9  # allow small drift
    assert t.remaining >= PHASE_DURATIONS[Phase.FOCUS] - 11


def test_tick_when_idle_returns_none():
    t = PomodoroTimer()
    assert t.tick() is None


def test_tick_when_paused_returns_none():
    t = PomodoroTimer()
    t.start()
    t.pause()
    assert t.tick() is None


def test_phase_transition_focus_to_break():
    t = PomodoroTimer()
    t.start()
    # Simulate full focus duration
    t.elapsed = PHASE_DURATIONS[Phase.FOCUS]
    t._last_tick = time.monotonic()
    transition = t.tick()
    assert transition is not None
    assert transition.finished_phase == Phase.FOCUS
    assert transition.completed is True
    assert transition.next_phase == Phase.BREAK
    assert transition.focus_count == 1
    # Timer auto-advances
    assert t.phase == Phase.BREAK
    assert t.state == TimerState.RUNNING
    assert t.elapsed < 1.0


def test_long_break_after_two_focus():
    t = PomodoroTimer()
    t.start()

    # Focus 1 → Break (auto-start)
    t.elapsed = PHASE_DURATIONS[Phase.FOCUS]
    t._last_tick = time.monotonic()
    tr1 = t.tick()
    assert tr1.next_phase == Phase.BREAK
    assert t.state == TimerState.RUNNING
    assert t.focus_count == 1

    # Break → IDLE (need manual start for Focus 2)
    t.elapsed = PHASE_DURATIONS[Phase.BREAK]
    t._last_tick = time.monotonic()
    tr2 = t.tick()
    assert tr2.next_phase == Phase.FOCUS
    assert t.state == TimerState.IDLE

    # Manual start Focus 2
    t.start()
    assert t.state == TimerState.RUNNING
    assert t.focus_count == 1  # preserved from before

    # Focus 2 → Long Break (auto-start)
    t.elapsed = PHASE_DURATIONS[Phase.FOCUS]
    t._last_tick = time.monotonic()
    tr3 = t.tick()
    assert tr3.next_phase == Phase.LONG_BREAK
    assert t.state == TimerState.RUNNING
    assert t.focus_count == 2


def test_pause_resume_preserves_elapsed():
    t = PomodoroTimer()
    t.start()
    # Simulate 60 seconds
    t._last_tick = time.monotonic() - 60
    t.tick()
    elapsed_before = t.elapsed

    t.pause()
    assert t.state == TimerState.PAUSED

    # Time passes while paused — should not count
    t.resume()
    assert t.state == TimerState.RUNNING
    # elapsed should be very close to what it was before pause
    # (resume resets _last_tick so no drift)
    t._last_tick = time.monotonic()  # simulate immediate tick
    assert abs(t.elapsed - elapsed_before) < 1.0


def test_skip_returns_transition_with_completed_false():
    t = PomodoroTimer()
    t.start()
    t.elapsed = 60.0  # 1 minute in
    transition = t.skip()
    assert transition is not None
    assert transition.completed is False
    assert transition.finished_phase == Phase.FOCUS
    assert transition.duration_seconds == 60
    assert t.phase == Phase.BREAK  # advanced to break
    assert t.state == TimerState.RUNNING  # break auto-starts


def test_skip_when_idle_returns_none():
    t = PomodoroTimer()
    assert t.skip() is None


def test_skip_when_paused():
    t = PomodoroTimer()
    t.start()
    t.pause()
    transition = t.skip()
    assert transition is not None
    # Skipped focus → goes to break (auto-start)
    assert t.phase == Phase.BREAK
    assert t.state == TimerState.RUNNING


def test_reset_clears_everything():
    t = PomodoroTimer()
    t.start()
    t.elapsed = 300.0
    t.focus_count = 3
    t.phase = Phase.BREAK
    t.reset()
    assert t.state == TimerState.IDLE
    assert t.phase == Phase.FOCUS
    assert t.focus_count == 0
    assert t.elapsed == 0.0


def test_progress_property():
    t = PomodoroTimer()
    t.start()
    assert t.progress == 0.0
    t.elapsed = PHASE_DURATIONS[Phase.FOCUS] / 2
    assert abs(t.progress - 0.5) < 0.01
    t.elapsed = PHASE_DURATIONS[Phase.FOCUS]
    assert t.progress == 1.0


def test_display_round_during_focus():
    t = PomodoroTimer()
    t.start()
    assert t.display_round == 1  # focus_count=0, round=1
    t.focus_count = 2
    assert t.display_round == 3


def test_display_round_during_break():
    t = PomodoroTimer()
    t.start()
    # Advance to break
    t.elapsed = PHASE_DURATIONS[Phase.FOCUS]
    t._last_tick = time.monotonic()
    t.tick()
    assert t.phase == Phase.BREAK
    assert t.display_round == 1  # shows completed rounds


def test_full_cycle():
    """Run through Focus→Break→Focus→LongBreak with manual starts after breaks."""
    t = PomodoroTimer()
    t.start()
    phases = []

    for i in range(4):  # 4 phase transitions
        t.elapsed = PHASE_DURATIONS[t.phase]
        t._last_tick = time.monotonic()
        tr = t.tick()
        assert tr is not None
        phases.append((tr.finished_phase, tr.next_phase))
        # After break ends, need manual start for next focus
        if t.state == TimerState.IDLE:
            t.start()

    assert phases == [
        (Phase.FOCUS, Phase.BREAK),       # round 1
        (Phase.BREAK, Phase.FOCUS),
        (Phase.FOCUS, Phase.LONG_BREAK),  # round 2
        (Phase.LONG_BREAK, Phase.FOCUS),
    ]
    assert t.focus_count == LONG_BREAK_INTERVAL
