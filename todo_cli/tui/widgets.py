from __future__ import annotations

from rich.text import Text
from textual.widgets import Static, Tree

from ..models import TodoEntity
from ..pomodoro import PHASE_LABELS, Phase, PomodoroTimer, TimerState
from ..tree import format_time


BOT_DIVIDER = "\n---\n🤖 bot:\n"


class TodoTree(Tree[int]):
    """Tree subclass that aligns leaf nodes with expandable nodes."""

    guide_depth = 4
    show_root = True
    can_focus = True

    def render_label(self, node, base_style, style):
        node_label = node.label.copy()
        node_label.stylize(style)
        if node == self.cursor_node:
            if node_label.spans:
                s = node_label.spans[0]
                node_label.stylize("rgb(255,165,0) bold", s.start, s.end)
            node_label.stylize("underline")
        text = Text.assemble(node_label)
        return text

    def _on_click(self, event) -> None:
        event.prevent_default()
        event.stop()

    def _on_mouse_down(self, event) -> None:
        event.prevent_default()
        event.stop()

    def _on_mouse_move(self, event) -> None:
        event.prevent_default()
        event.stop()


def _render_label(todo: TodoEntity, is_leaf: bool = True, desc_count: tuple[int, int] | None = None, bot_running: set[int] | None = None) -> Text:
    time_str = format_time(todo.done_at if todo.done else todo.created)
    text = Text(style="dim" if todo.done else "")
    if todo.pinned:
        text.append("★ ", style="yellow bold")
    text.append(todo.text, style="strike" if todo.done else "")
    text.append(f" #{todo.id}", style="dim")
    if desc_count:
        done, total = desc_count
        text.append(f" [{done}/{total}]", style="dim italic")
    if todo.desc:
        text.append(" ℹ", style="dim")
    if bot_running and todo.id in bot_running:
        text.append(" 💭")
    elif todo.desc and BOT_DIVIDER in todo.desc:
        text.append(" 🤖")
    if time_str:
        style = "green italic" if todo.done else "dim italic"
        text.append(f"  {time_str}", style=style)
    return text


class PomodoroBar(Static):
    """Pomodoro progress bar, docked below Header."""

    DEFAULT_CSS = """
    PomodoroBar {
        dock: top;
        height: 1;
        padding: 0 1;
        display: none;
    }
    PomodoroBar.pomodoro-focus {
        background: darkred;
        color: white;
        display: block;
    }
    PomodoroBar.pomodoro-break {
        background: darkgreen;
        color: white;
        display: block;
    }
    PomodoroBar.pomodoro-long-break {
        background: darkcyan;
        color: white;
        display: block;
    }
    PomodoroBar.pomodoro-flash {
        background: $warning;
        color: black;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._flash_count = 0

    def refresh_display(self, timer: PomodoroTimer) -> None:
        self.remove_class("pomodoro-focus", "pomodoro-break", "pomodoro-long-break")
        if timer.state == TimerState.IDLE:
            return

        phase_class = {
            Phase.FOCUS: "pomodoro-focus",
            Phase.BREAK: "pomodoro-break",
            Phase.LONG_BREAK: "pomodoro-long-break",
        }
        self.add_class(phase_class[timer.phase])

        label = PHASE_LABELS[timer.phase]
        mins, secs = divmod(timer.remaining, 60)
        time_str = f"{mins:02d}:{secs:02d}"

        bar_width = max(20, self.size.width - len(label) - 30)
        filled = int(bar_width * timer.progress)
        empty = bar_width - filled
        bar = "○" * filled + "·" * empty

        paused = " PAUSED" if timer.state == TimerState.PAUSED else ""

        text = Text()
        text.append("\U0001f345 ", style="bold")
        text.append(f"{label}  ", style="bold")
        text.append(f"[{bar}]  ")
        text.append(f"{time_str}  ", style="bold")
        text.append(f"Round {timer.display_round}", style="italic")
        if paused:
            text.append(paused, style="bold yellow")

        self.update(text)

    def flash(self) -> None:
        self._flash_count = 6
        self._do_flash()

    def _do_flash(self) -> None:
        if self._flash_count <= 0:
            self.remove_class("pomodoro-flash")
            return
        if self._flash_count % 2 == 0:
            self.add_class("pomodoro-flash")
        else:
            self.remove_class("pomodoro-flash")
        self._flash_count -= 1
        self.set_timer(0.2, self._do_flash)
