from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown

from ..pomodoro import TimerState


class InputScreen(ModalScreen[str]):
    """底部弹出输入框。"""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, prompt: str = "New todo", default: str = "") -> None:
        super().__init__()
        self.prompt = prompt
        self.default = default

    def compose(self) -> ComposeResult:
        yield Input(placeholder=self.prompt, value=self.default)

    def on_mount(self) -> None:
        inp = self.query_one(Input)
        inp.focus()
        if self.default:
            inp.cursor_position = len(self.default)

    @on(Input.Submitted)
    def on_submit(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)
        else:
            self.dismiss("")

    def on_key(self, event) -> None:
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")


class ConfirmScreen(ModalScreen[bool]):
    """确认对话框。"""

    BINDINGS = [
        Binding("y", "yes", "Yes", priority=True),
        Binding("n", "no", "No", priority=True),
        Binding("escape", "no", "Cancel", priority=True),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Label(self.message)

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class InfoScreen(ModalScreen[str | None]):
    """只读信息弹窗，按任意键关闭。"""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("i", "close", "Close", priority=True),
        Binding("b", "dispatch", "Bot", priority=True),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body

    def compose(self) -> ComposeResult:
        yield Label(self.title_text)
        yield Markdown(self.body_text)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_dispatch(self) -> None:
        self.dismiss("dispatch")


class PomodoroMenuScreen(ModalScreen[str]):
    """Pomodoro control menu."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("s", "select_start", "Start", priority=True),
        Binding("p", "select_pause", "Pause", priority=True),
        Binding("c", "select_resume", "Continue", priority=True),
        Binding("n", "select_skip", "Next", priority=True),
        Binding("x", "select_reset", "Reset", priority=True),
        Binding("o", "select_history", "History", priority=True),
    ]

    def __init__(self, timer_state: TimerState) -> None:
        super().__init__()
        self.timer_state = timer_state

    def compose(self) -> ComposeResult:
        if self.timer_state == TimerState.IDLE:
            msg = "\U0001f345 Pomodoro\n\n  \\[S]tart  \\[O] History\n  \\[Esc] Cancel"
        elif self.timer_state == TimerState.RUNNING:
            msg = "\U0001f345 Pomodoro (Running)\n\n  \\[P]ause  \\[N]ext  \\[X] Reset  \\[O] History\n  \\[Esc] Cancel"
        else:
            msg = "\U0001f345 Pomodoro (Paused)\n\n  \\[C]ontinue  \\[N]ext  \\[X] Reset  \\[O] History\n  \\[Esc] Cancel"
        yield Label(msg)

    def action_cancel(self) -> None:
        self.dismiss("")

    def action_select_start(self) -> None:
        if self.timer_state == TimerState.IDLE:
            self.dismiss("start")

    def action_select_pause(self) -> None:
        if self.timer_state == TimerState.RUNNING:
            self.dismiss("pause")

    def action_select_resume(self) -> None:
        if self.timer_state == TimerState.PAUSED:
            self.dismiss("resume")

    def action_select_skip(self) -> None:
        if self.timer_state != TimerState.IDLE:
            self.dismiss("skip")

    def action_select_reset(self) -> None:
        if self.timer_state != TimerState.IDLE:
            self.dismiss("reset")

    def action_select_history(self) -> None:
        self.dismiss("history")
