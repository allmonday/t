# Claude Dispatch from Todo InfoScreen

## Context

Users want to leverage Claude AI directly from individual todos to get analysis, suggestions, or elaborations on their tasks. Currently, the `i` key opens a read-only InfoScreen showing the todo's description. This feature adds a `b` keybinding inside that screen to dispatch the todo's text + description to `claude -p` as a subprocess, then append the response back into the description field.

## Requirements

- Dispatch Claude from the InfoScreen via `b` keybinding
- Prompt is constructed from `todo.text` + `todo.desc` (desc may be empty)
- Uses `claude -p` CLI subprocess (no SDK dependency)
- While running: 💭 emoji on the todo's tree label
- On completion: append response to `desc` with divider, show 🤖 emoji on label
- One dispatch per todo at a time; multiple todos can run in parallel
- Non-blocking: the TUI remains fully interactive during execution

## Architecture

### Approach: Textual Worker + asyncio subprocess

Uses `asyncio.create_subprocess_exec` to run `claude -p` non-blockingly, managed by Textual's worker system. This matches the codebase's existing async patterns (all store methods are async, workers are used for modal screens).

### Components Modified

#### 1. `tui.py` — `TodoApp` class

**New state:**
```python
self._bot_running: set[int] = set()
```

Tracks todo IDs with active Claude subprocesses. Used by the label renderer for 💭 icon and by the dispatch function to prevent double-dispatch. A simple `set[int]` suffices — no need to store the `Process` object since we don't support cancellation.

**New constant:**
```python
BOT_DIVIDER = "\n---\n🤖 bot:\n"
```

Used both for appending results and for detection in `_render_label`. Defined once to avoid divergence.

**New method: `_dispatch_claude(todo_id: int)`**

```
async def _dispatch_claude(todo_id):
    1. Guard: if todo_id in self._bot_running → notify("Already running") and return
    2. Fetch todo from store
    3. Build prompt:
       - If desc exists: f"Todo: {todo.text}\n\nDescription:\n{todo.desc}"
       - If no desc: f"Todo: {todo.text}"
    4. self._bot_running.add(todo_id)
    5. Update tree labels (shows 💭)
    6. try:
        a. Spawn: asyncio.create_subprocess_exec(
               "claude", "-p", prompt,
               stdout=asyncio.subprocess.PIPE,
               stderr=asyncio.subprocess.PIPE
           )
        b. stdout, stderr = await process.communicate()
        c. On success (returncode == 0):
           - Build response block: BOT_DIVIDER + stdout.decode().strip()
           - Fetch fresh todo from store (desc may have changed)
           - Append response to current desc (or set as desc if was None)
           - await store.update_desc(todo_id, new_desc)
           - notify(f"Bot replied on #{todo_id}")
        d. On failure:
           - notify(f"Claude failed: {stderr.decode()[:100]}")
    7. except FileNotFoundError:
        - notify("claude CLI not found")
    8. finally:
        - self._bot_running.discard(todo_id)
        - Update tree labels (💭 removed, 🤖 visible via desc content)
```

Launched via `self.run_worker(self._dispatch_claude(todo_id))`.

#### 2. `tui.py` — `InfoScreen` class

**Change return type** from `ModalScreen[None]` to `ModalScreen[str | None]`.

**Add keybinding:**
```python
Binding("b", "dispatch", "Bot")
```

**Add action:**
```python
def action_dispatch(self) -> None:
    self.dismiss("dispatch")
```

#### 3. `tui.py` — `_show_info()` method

**Change behavior when desc is empty:** Currently returns early with "No description" notification. New behavior: open InfoScreen with an empty body so the user can still press `b` to dispatch.

After `push_screen_wait(InfoScreen(...))`, check the return value:
```python
result = await self.push_screen_wait(InfoScreen(f"#{todo.id} {todo.text}", todo.desc or ""))
if result == "dispatch":
    self.run_worker(self._dispatch_claude(todo_id))
```

Note: The existing pomodoro history caller of InfoScreen (`_show_pomodoro_history`, line 932) ignores the return value from `push_screen_wait`, so changing InfoScreen's return type is safe.

#### 4. `tui.py` — `_render_label()` function

Add a `bot_running: set[int]` parameter (set of todo IDs currently dispatching).

After the existing `ℹ` icon logic:
```python
if todo.id in bot_running:
    text.append(" 💭")
elif todo.desc and BOT_DIVIDER in todo.desc:
    text.append(" 🤖")
```

Note: `_render_label` is a module-level free function. Adding `bot_running: set[int]` as a parameter is consistent with how `desc_count` is already passed — display hints that come from app-level state.

#### 5. `tui.py` — All `_render_label()` call sites

Pass `bot_running=self._bot_running` to `_render_label()`.

This affects `_refresh_tree()` (line ~505) and `_update_labels()` (line ~551).

### Data Flow

```
[InfoScreen] --dismiss("dispatch")--> [_show_info]
    --> [_dispatch_claude] as worker
        --> _bot_running.add(id)  (💭 appears)
        --> asyncio.create_subprocess_exec("claude", "-p", prompt)
        --> await process.communicate()
        --> store.update_desc(id, desc + BOT_DIVIDER + response)  (🤖 appears)
        --> finally: _bot_running.discard(id)
        --> notify("Bot replied")
```

### Edge Cases

| Case | Behavior |
|------|----------|
| No desc on todo | Dispatch with just `todo.text` as prompt |
| `claude` CLI not found | `FileNotFoundError` caught, notify user |
| Process error (non-zero exit) | Notify with truncated stderr |
| Double-dispatch on same todo | Guard check, notify "Already running" |
| Todo deleted while dispatch running | Process completes but `store.update_desc` silently fails (todo not found) |
| App quit while dispatch running | Process is killed by OS when parent exits |
| Very large response | Appended as-is; no truncation (desc is TEXT column, no limit) |

### Files to Modify

| File | Change |
|------|--------|
| `todo_cli/tui.py` | InfoScreen return type + `b` binding, `_dispatch_claude()`, `_show_info()` dispatch handling + empty-desc support, `_render_label()` emoji logic, `_bot_running` state, `BOT_DIVIDER` constant |

### Files NOT Modified

- `models.py` — no schema changes needed (desc is already TEXT)
- `store.py` — `update_desc()` already exists and works for appending
- `tree.py` — label rendering is in `tui.py`, not here

## Verification

1. **Happy path:** Create a todo with description, press `i` then `b`, verify 💭 appears, wait for response, verify 🤖 appears and desc is updated
2. **No desc:** Create a todo without description, press `i`, verify InfoScreen opens with empty body, press `b`, verify it dispatches with just the title
3. **Double dispatch:** While 💭 is showing, press `i` then `b` again, verify "Already running" notification
4. **Parallel:** Dispatch on two different todos, verify both show 💭, both complete independently
5. **Error handling:** Test with `claude` not in PATH, verify error notification
6. **Label persistence:** After bot reply, close and reopen the app, verify 🤖 still shows (it's in the desc content)
