# Pomodoro Timer — Design Spec

## Context

The todo TUI app needs a built-in Pomodoro timer to help manage focus/break rhythms directly in the terminal. The timer is global (not tied to specific todos), with fixed parameters and a dedicated progress bar UI.

## Requirements

- **Global independent timer** — not associated with any todo item
- **Fixed cycle:** Focus 25min → Break 5min → Focus 25min → Long Break 15min → repeat
- **UI:** Dedicated progress bar below Header, hidden when inactive
  - Focus: red background, Break: green, Long Break: cyan
  - Shows: phase label, ASCII progress bar, MM:SS remaining, round counter
- **Controls:** `P` key opens modal menu (Start / Pause / Resume / Reset / Skip)
- **Notification:** Desktop notification via `notify-send` when a phase ends
- **Persistence:** Record completed/skipped sessions to SQLite via Alembic migration

## Architecture

```
pomodoro.py (pure logic)     →  tui.py (UI integration)
  PomodoroTimer                   PomodoroBar (Static widget)
  Phase enum                      PomodoroMenuScreen (modal)
  PhaseTransition dataclass       _pomodoro_tick() callback

models.py                    →  store.py
  PomodoroSessionORM              PomodoroStore (separate class,
  PomodoroSessionEntity            same session_factory pattern)
```

### Separation of Concerns

- `pomodoro.py` — Pure state machine. No UI, no asyncio, no DB imports. Uses `time.monotonic()` for drift-free timing. Exposes a polling `tick()` interface.
- `tui.py` — Thin integration: calls `tick()` via `set_interval(1.0)`, renders the bar, handles menu interactions, dispatches notifications and DB writes.

## State Machine

### Phases and Durations

| Phase | Duration | When |
|---|---|---|
| FOCUS | 25 min | Default working phase |
| BREAK | 5 min | After odd-numbered focus rounds |
| LONG_BREAK | 15 min | After every 2nd focus round |

### States

| State | Description |
|---|---|
| IDLE | Not started. Bar hidden. |
| RUNNING | Timer counting down. Bar visible. |
| PAUSED | Timer frozen. Bar visible (paused indicator). |

### Transitions

- `start()` — IDLE → RUNNING (begins FOCUS phase)
- `pause()` — RUNNING → PAUSED
- `resume()` — PAUSED → RUNNING
- `reset()` — Any → IDLE (discards current session, no DB write)
- `skip()` — RUNNING/PAUSED → advance to next phase (records with completed=False)
- `tick()` — When elapsed >= duration: auto-advance to next phase (records with completed=True)

Phase completion returns a `PhaseTransition` dataclass containing the finished phase info and the next phase. The timer auto-starts the next phase (stays RUNNING).

### focus_count and Round Display

`focus_count` increments when a FOCUS phase **completes** (via tick or skip). It determines when to trigger a long break: `focus_count % 2 == 0` → long break.

UI displays "Round N" where N = `focus_count + 1` (during a FOCUS phase) or `focus_count` (during a break, showing completed rounds).

### Cycle Example

```
Start → FOCUS(25m) [focus_count=0, displays "Round 1"]
  tick completes → focus_count becomes 1
    1 % 2 != 0 → BREAK(5m)  [displays "Round 1"]
  tick completes → FOCUS(25m) [focus_count=1, displays "Round 2"]
  tick completes → focus_count becomes 2
    2 % 2 == 0 → LONG_BREAK(15m) [displays "Round 2"]
  tick completes → FOCUS(25m) [focus_count=2, displays "Round 3"]
  ...
```

## Data Model

### New Table: `pomodoro_sessions`

```sql
CREATE TABLE pomodoro_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,          -- ISO 8601
    finished_at TEXT NOT NULL,         -- ISO 8601
    phase TEXT NOT NULL,               -- "focus" | "break" | "long_break"
    duration_seconds INTEGER NOT NULL, -- actual elapsed seconds
    completed INTEGER NOT NULL DEFAULT 1  -- 1=completed, 0=skipped
);
CREATE INDEX idx_pomodoro_started ON pomodoro_sessions(started_at);
```

New Alembic migration with `down_revision = "d75c6f862ec4"`.

### Pydantic Entity

```python
class PomodoroSessionEntity(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    started_at: str
    finished_at: str
    phase: str               # "focus" | "break" | "long_break"
    duration_seconds: int
    completed: bool = True
```

### PomodoroStore

A separate class in `store.py` (not mixed into `TodoStore`), following the same `session_factory` injection pattern:

```python
class PomodoroStore:
    def __init__(self, session_factory): ...
    async def record_session(self, started_at, finished_at, phase, duration_seconds, completed) -> PomodoroSessionEntity: ...
```

Instantiated in `TodoApp.__init__` alongside `TodoStore`, using the same `session_factory`.

## UI Components

### PomodoroBar (Static widget)

- Docked below Header (`dock: top`)
- `display: none` when IDLE
- CSS classes toggle background color: `pomodoro-focus` (red), `pomodoro-break` (green), `pomodoro-long-break` (cyan)
- Renders: `FOCUS  [=========>          ]  18:32  Round 1`

### PomodoroMenuScreen (ModalScreen)

Follows existing modal pattern (ConfirmScreen style). Shows contextual actions based on timer state:

- IDLE: **S**tart
- RUNNING: **P**ause | S**k**ip | Re**s**et
- PAUSED: **R**esume | S**k**ip | Re**s**et

Key bindings: `s`=**S**tart, `p`=**P**ause, `r`=**R**esume, `k`=s**K**ip, `x`=reset(e**X**it timer) + `escape` to cancel.

### Layout Change

```python
def compose(self) -> ComposeResult:
    yield Header()
    yield PomodoroBar()      # NEW — hidden by default
    yield TodoTree("TODO")
    yield Static("", id="status-bar")
    yield Footer()
```

### Key Binding

`P` (uppercase) → `action_pomodoro_menu`

## Desktop Notification

```python
subprocess.run(["notify-send", title, body], timeout=5, capture_output=True)
```

Wrapped in try/except for `FileNotFoundError` and `TimeoutExpired`. Silent failure if `notify-send` not available.

## Edge Cases

- **App exit during timer:** Current session discarded (not recorded). Intentional — partial sessions are not meaningful.
- **Modal screens active:** `set_interval` still fires on the underlying app. Timer continues during input dialogs.
- **Reset during break:** Returns to IDLE, focus_count resets to 0. Interrupted session not recorded.
- **Skip:** Records session with `completed=False`, advances to next phase, stays RUNNING.
- **Timer accuracy:** `time.monotonic()` deltas in `tick()` ensure accuracy regardless of `set_interval` jitter.

## Files Changed

| File | Action | ~Lines |
|---|---|---|
| `todo_cli/pomodoro.py` | CREATE | 140 |
| `todo_cli/models.py` | MODIFY | +25 |
| `todo_cli/store.py` | MODIFY | +35 |
| `todo_cli/tui.py` | MODIFY | +180 |
| `todo_cli/alembic/versions/..._add_pomodoro_sessions.py` | CREATE | 30 |
| `tests/test_pomodoro.py` | CREATE | 120 |
| `tests/test_store.py` | MODIFY | +20 |
| `tests/test_tui.py` | MODIFY | +30 |

## Verification

1. Run `pytest` — all existing + new tests pass
2. Launch TUI (`t` is the installed CLI command), press `P`, select Start — bar appears with red background and countdown
3. Wait or skip through a full cycle: Focus → Break → Focus → Long Break
4. Verify desktop notification fires at each transition
5. Check DB: `sqlite3 ~/.todo.db "SELECT * FROM pomodoro_sessions"`
6. Press `P` → Reset — bar disappears, timer returns to IDLE
7. Press `q` during active timer — app exits cleanly, no crash
