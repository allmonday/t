from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Static, Tree
from textual.widgets.tree import TreeNode

from .client import TodoClient, TodoClientError
from .models import TodoEntity
from .pomodoro import DEFAULT_DURATIONS, PHASE_LABELS, Phase, PhaseTransition, PomodoroTimer, TimerState
from .tree import build_children_map, count_descendants, filter_todos, format_time


# ── constants ──

BOT_DIVIDER = "\n---\n🤖 bot:\n"

# ── helpers ──


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

    # 屏蔽鼠标事件，仅支持键盘交互
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
    time = format_time(todo.created)
    if todo.done:
        text = Text(style="dim")
        text.append(f"#{todo.id} ")
        text.append(todo.text, style="strike")
        if desc_count:
            done, total = desc_count
            text.append(f" [{done}/{total}]", style="dim italic")
        if todo.desc:
            text.append(" \u2139", style="dim")
        if bot_running and todo.id in bot_running:
            text.append(" 💭")
        elif todo.desc and BOT_DIVIDER in todo.desc:
            text.append(" 🤖")
        if todo.done_at:
            done_time = format_time(todo.done_at)
            if done_time:
                text.append(f"  {done_time}", style="green italic")
    else:
        text = Text()
        text.append(f"#{todo.id} ", style="dim")
        text.append(todo.text)
        if desc_count:
            done, total = desc_count
            text.append(f" [{done}/{total}]", style="dim")
        if todo.desc:
            text.append(" \u2139", style="dim")
        if bot_running and todo.id in bot_running:
            text.append(" 💭")
        elif todo.desc and BOT_DIVIDER in todo.desc:
            text.append(" 🤖")
        if time:
            text.append(f"  {time}", style="dim italic")
    return text


# ── screens ──


class InputScreen(ModalScreen[str]):
    """底部弹出输入框。"""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

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
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "Cancel"),
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
        Binding("escape", "close", "Close"),
        Binding("i", "close", "Close"),
        Binding("b", "dispatch", "Bot"),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body_text = body

    def compose(self) -> ComposeResult:
        yield Label(f"{self.title_text}\n\n{self.body_text}")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_dispatch(self) -> None:
        self.dismiss("dispatch")


# ── pomodoro widgets ──


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
        bar = "\u25cb" * filled + "\u00b7" * empty

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
        """Flash the bar to signal phase completion."""
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


class PomodoroMenuScreen(ModalScreen[str]):
    """Pomodoro control menu."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("s", "select_start", "Start"),
        Binding("p", "select_pause", "Pause"),
        Binding("c", "select_resume", "Continue"),
        Binding("n", "select_skip", "Next"),
        Binding("x", "select_reset", "Reset"),
        Binding("o", "select_history", "History"),
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


# ── main app ──


class TodoApp(App):
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        layout: vertical;
    }
    * {
        scrollbar-size: 0 0;
    }
    TodoTree {
        height: 1fr;
        margin: 0 0 0 1;
        background: transparent;
    }
    TodoTree > .tree--cursor {
        background: transparent;
        text-style: none;
    }
    TodoTree > .tree--highlight {
        background: transparent;
        text-style: none;
    }
    TodoTree > .tree--line:hover {
        background: transparent;
        text-style: none;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    InputScreen {
        align: center bottom;
    }
    InputScreen Input {
        width: 80%;
        margin: 1;
    }
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen Label {
        width: auto;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    InfoScreen {
        align: center middle;
    }
    InfoScreen Label {
        width: auto;
        max-width: 80%;
        padding: 1 2;
        background: $surface;
        border: round $accent;
    }
    PomodoroMenuScreen {
        align: center middle;
    }
    PomodoroMenuScreen Label {
        width: auto;
        padding: 1 2;
        background: $surface;
        border: round $primary;
    }
    """

    TITLE = "TODO"

    BINDINGS = [
        Binding("k", "cursor_up", "Up", show=False, priority=True),
        Binding("j", "cursor_down", "Down", show=False, priority=True),
        Binding("g", "press_g", show=False, priority=True),
        Binding("G", "goto_bottom", "Bottom", show=False, priority=True),
        Binding("a", "add_sibling", "Add"),
        Binding("A", "add_root", "Add Root"),
        Binding("tab", "add_child", "Sub-task", priority=True),
        Binding("d", "delete_todo", "Delete"),
        Binding("e", "edit_todo", "Edit"),
        Binding("i", "show_info", "Info"),
        Binding("space", "toggle_todo", "Toggle", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("h", "press_h", "Collapse", priority=True),
        Binding("left", "collapse_node", "Collapse", show=False, priority=True),
        Binding("l", "press_l", "Expand", priority=True),
        Binding("right", "expand_node", "Expand", show=False, priority=True),
        Binding("m", "toggle_all", "Fold/Unfold All", priority=True),
        Binding("f", "cycle_filter", "Filter"),
        Binding("colon", "goto_id", "Goto #", priority=True),
        Binding("S", "toggle_stale", "Archived"),
        Binding("T", "toggle_theme", "Theme"),
        Binding("P", "pomodoro_menu", "Pomo"),
        Binding("q", "quit", "Quit"),
    ]

    _UI_STATE_PATH = os.path.expanduser("~/.todo_ui_state.json")
    _THEMES = [
        "gruvbox",
        "dracula",
        "textual-dark",
        "nord",
    ]

    def __init__(self, client: TodoClient, pomo_durations: dict[Phase, int] | None = None) -> None:
        super().__init__()
        self.client = client
        self._filter_labels = ["All", "Pending"]
        self._filter_values: list[bool | None] = [None, False]
        self._hide_stale: bool = True
        self._g_pending: bool = False
        self._l_pending: bool = False
        self._h_pending: bool = False
        self._pomodoro = PomodoroTimer(durations=pomo_durations)
        self._bot_running: set[int] = set()
        ui_state = self._load_ui_state()
        self._saved_expanded: set[int] = ui_state.get("expanded", set())
        self._saved_theme: str = ui_state.get("theme", self._THEMES[0])
        self._filter_mode: int = min(ui_state.get("filter_mode", 0), 1)

    def compose(self) -> ComposeResult:
        yield Header()
        yield PomodoroBar()
        yield TodoTree("TODO")
        yield Static("", id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        self.theme = self._saved_theme
        self._update_header()
        await self._refresh_tree(force_expand=self._saved_expanded)
        self.set_interval(1.0, self._pomodoro_tick)

    def _update_header(self) -> None:
        self.title = "TODO"
        label = self._filter_labels[self._filter_mode]
        stale_label = "hidden" if self._hide_stale else "shown"
        self.sub_title = f"Filter: {label}  |  Archived: {stale_label}"
        self.query_one("#status-bar", Static).update(f"Theme: {self.theme}")

    def _load_ui_state(self) -> dict:
        try:
            with open(self._UI_STATE_PATH, "r") as f:
                data = json.load(f)
            return {
                "expanded": set(data.get("expanded", [])),
                "theme": data.get("theme", self._THEMES[0]),
                "filter_mode": data.get("filter_mode", 0),
            }
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return self._migrate_pickle_state()

    def _migrate_pickle_state(self) -> dict:
        pickle_path = os.path.expanduser("~/.todo_ui_state.pkl")
        try:
            import pickle
            with open(pickle_path, "rb") as f:
                data = pickle.load(f)
            result: dict = {"expanded": set(), "theme": self._THEMES[0]}
            if isinstance(data, set):
                result["expanded"] = data
            elif isinstance(data, dict):
                result["expanded"] = data.get("expanded", set())
                result["theme"] = data.get("theme", self._THEMES[0])
            os.remove(pickle_path)
            return result
        except (FileNotFoundError, Exception):
            return {"expanded": set(), "theme": self._THEMES[0]}

    def _save_ui_state(self) -> None:
        tree = self.query_one(TodoTree)
        expanded_ids: set[int] = set()
        for node in tree.root.children:
            self._collect_expanded(node, expanded_ids)
        state = {"expanded": sorted(expanded_ids), "theme": self.theme, "filter_mode": self._filter_mode}
        with open(self._UI_STATE_PATH, "w") as f:
            json.dump(state, f)

    async def action_quit(self) -> None:
        self._save_ui_state()
        await self.client.close()
        self.exit()

    # ── tree building ──

    async def _refresh_tree(self, select_id: int | None = None, force_expand: set[int] | None = None) -> None:
        tree = self.query_one(TodoTree)

        # 保存当前展开状态
        expanded_ids: set[int] = set()
        for node in tree.root.children:
            self._collect_expanded(node, expanded_ids)
        if force_expand:
            expanded_ids |= force_expand

        # 先查数据，再清空树，避免 clear 和重建之间有 await 导致闪烁
        filter_done = self._filter_values[self._filter_mode]
        todos = await self.client.list_active()
        todos = filter_todos(todos, filter_done=filter_done, hide_stale=self._hide_stale)
        children_map = build_children_map(todos)
        desc_counts = count_descendants(children_map)

        tree.clear()
        count = len(todos)
        suffix = f" {self._filter_labels[self._filter_mode].lower()}" if self._filter_mode else ""
        tree.root.set_label(f"[bold cyan]TODO[/bold cyan] ({count} items{suffix})")
        tree.root.expand()

        node_map: dict[int, TreeNode[int]] = {}

        def add_nodes(parent_node: TreeNode[int], parent_id: int | None) -> None:
            for todo in children_map.get(parent_id, []):
                has_children = todo.id in children_map
                label = _render_label(todo, is_leaf=not has_children, desc_count=desc_counts.get(todo.id), bot_running=self._bot_running)
                if has_children:
                    node = parent_node.add(label, data=todo.id, expand=(todo.id in expanded_ids))
                else:
                    node = parent_node.add_leaf(label, data=todo.id)
                node_map[todo.id] = node
                add_nodes(node, todo.id)

        add_nodes(tree.root, None)

        # restore cursor
        if select_id and select_id in node_map:
            node = node_map[select_id]
            # 检查所有祖先是否已展开，避免意外展开
            visible = True
            parent = node.parent
            while parent is not None and parent != tree.root:
                if not parent.is_expanded:
                    visible = False
                    break
                parent = parent.parent
            if visible:
                def _restore_cursor(n=node):
                    tree.select_node(n)
                    tree.scroll_to_node(n)

                self.call_after_refresh(_restore_cursor)

    @staticmethod
    def _collect_expanded(node: TreeNode[int], expanded_ids: set[int]) -> None:
        if node.data is not None and node.is_expanded:
            expanded_ids.add(node.data)
        for child in node.children:
            TodoApp._collect_expanded(child, expanded_ids)

    async def _update_labels(self) -> None:
        """就地更新所有节点标签，不重建树，光标位置不变。仅用于 edit 场景。"""
        tree = self.query_one(TodoTree)
        todo_list = await self.client.list_active()
        todos = {t.id: t for t in todo_list}
        children_map = build_children_map(todo_list)
        desc_counts = count_descendants(children_map)

        def walk(node: TreeNode[int]) -> None:
            if node.data is not None and node.data in todos:
                is_leaf = not bool(node.children)
                node.set_label(_render_label(todos[node.data], is_leaf=is_leaf, desc_count=desc_counts.get(node.data), bot_running=self._bot_running))
            for child in node.children:
                walk(child)

        walk(tree.root)
        suffix = f" {self._filter_labels[self._filter_mode].lower()}" if self._filter_mode else ""
        count = len(todos)
        tree.root.set_label(f"[bold cyan]TODO[/bold cyan] ({count} items{suffix})")

    def _get_selected_todo_id(self) -> int | None:
        tree = self.query_one(TodoTree)
        node = tree.cursor_node
        if node and node.data is not None:
            return node.data
        return None

    # ── actions ──

    def action_press_g(self) -> None:
        if self._g_pending:
            self._g_pending = False
            tree = self.query_one(TodoTree)
            tree.scroll_home(animate=False)
            tree.move_cursor_to_line(0)
        else:
            self._g_pending = True
            self.set_timer(0.3, self._reset_g)

    def _reset_g(self) -> None:
        self._g_pending = False

    def action_goto_bottom(self) -> None:
        self._g_pending = False
        tree = self.query_one(TodoTree)
        tree.action_scroll_end()
        tree.move_cursor_to_line(tree.last_line)

    def action_cursor_up(self) -> None:
        self.query_one(TodoTree).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one(TodoTree).action_cursor_down()

    async def _goto_id(self) -> None:
        text = await self.push_screen_wait(InputScreen("Goto #id"))
        if not text:
            return
        raw = text.strip().lstrip("#")
        try:
            todo_id = int(raw)
        except ValueError:
            return
        tree = self.query_one(TodoTree)

        def find_node(node: TreeNode[int]) -> TreeNode[int] | None:
            if node.data == todo_id:
                return node
            for child in node.children:
                found = find_node(child)
                if found:
                    return found
            return None

        target = find_node(tree.root)
        if target is None:
            self.notify(f"#{todo_id} not found", severity="warning")
            return
        # 检查所有祖先是否已展开，未展开则不跳转
        parent = target.parent
        while parent is not None and parent != tree.root:
            if not parent.is_expanded:
                self.notify(f"#{todo_id} is hidden", severity="warning")
                return
            parent = parent.parent
        tree.select_node(target)
        tree.scroll_to_node(target)

    async def action_goto_id(self) -> None:
        self.run_worker(self._goto_id())

    async def action_toggle_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        if await self.client.has_children(todo_id):
            self.notify("Has sub-tasks, toggle leaves only", severity="warning")
            return
        await self.client.toggle(todo_id)
        await self._update_labels()

    def action_collapse_node(self) -> None:
        tree = self.query_one(TodoTree)
        node = tree.cursor_node
        if node and node.is_expanded:
            node.collapse()

    def action_press_h(self) -> None:
        if self._h_pending:
            self._h_pending = False
            self.action_collapse_all_children()
        else:
            self._h_pending = True
            self.action_collapse_node()
            self.set_timer(0.3, self._reset_h)

    def _reset_h(self) -> None:
        self._h_pending = False

    def action_collapse_all_children(self) -> None:
        tree = self.query_one(TodoTree)
        node = tree.cursor_node
        if node:
            self._collapse_recursive(node)

    def action_expand_node(self) -> None:
        tree = self.query_one(TodoTree)
        node = tree.cursor_node
        if node and not node.is_expanded:
            node.expand()

    def action_press_l(self) -> None:
        if self._l_pending:
            self._l_pending = False
            self.action_expand_all_children()
        else:
            self._l_pending = True
            self.action_expand_node()
            self.set_timer(0.3, self._reset_l)

    def _reset_l(self) -> None:
        self._l_pending = False

    def action_expand_all_children(self) -> None:
        tree = self.query_one(TodoTree)
        node = tree.cursor_node
        if node:
            self._expand_recursive(node)

    def action_toggle_all(self) -> None:
        tree = self.query_one(TodoTree)
        has_expanded = any(
            node.is_expanded
            for node in tree.root.children
            if node.children
        )
        for node in tree.root.children:
            if has_expanded:
                self._collapse_recursive(node)
            else:
                self._expand_recursive(node)

    @staticmethod
    def _collapse_recursive(node: TreeNode[int]) -> None:
        for child in node.children:
            TodoApp._collapse_recursive(child)
        node.collapse()

    @staticmethod
    def _expand_recursive(node: TreeNode[int]) -> None:
        node.expand()
        for child in node.children:
            TodoApp._expand_recursive(child)

    async def _add_sibling(self, todo_id: int) -> None:
        todo = await self.client.get(todo_id)
        if not todo:
            return
        parent_id = todo.parent

        if parent_id:
            parent = await self.client.get(parent_id)
            prompt = f"Sibling of #{todo_id}" + (f" (under {parent.text[:20]})" if parent else "")
        else:
            prompt = "New root todo"
        text = await self.push_screen_wait(InputScreen(prompt))
        if text:
            new_todo = await self.client.add(text, parent_id=parent_id)
            await self._refresh_tree(select_id=new_todo.id)

    async def action_add_sibling(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            self.run_worker(self._add_root())
        else:
            self.run_worker(self._add_sibling(todo_id))

    async def _add_root(self) -> None:
        text = await self.push_screen_wait(InputScreen("New root todo"))
        if text:
            todo = await self.client.add(text)
            await self._refresh_tree(select_id=todo.id)

    async def action_add_root(self) -> None:
        self.run_worker(self._add_root())

    async def _add_child(self, todo_id: int) -> None:
        todo = await self.client.get(todo_id)
        prompt = f"Sub-task of #{todo_id}" + (f" ({todo.text[:20]})" if todo else "")
        text = await self.push_screen_wait(InputScreen(prompt))
        if text:
            new_todo = await self.client.add(text, parent_id=todo_id)
            await self._refresh_tree(select_id=new_todo.id, force_expand={todo_id})

    async def action_add_child(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            self.run_worker(self._add_root())
        else:
            self.run_worker(self._add_child(todo_id))

    async def _edit_todo(self, todo_id: int) -> None:
        todo = await self.client.get(todo_id)
        if not todo:
            return
        new_text = await self.push_screen_wait(InputScreen(f"Edit #{todo_id} text", default=todo.text))
        if new_text and new_text != todo.text:
            await self.client.update_text(todo_id, new_text)
        new_desc = await self.push_screen_wait(InputScreen(f"Edit #{todo_id} desc", default=todo.desc or ""))
        if new_desc and new_desc != (todo.desc or ""):
            await self.client.update_desc(todo_id, new_desc)
        await self._update_labels()

    async def action_edit_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        self.run_worker(self._edit_todo(todo_id))

    async def _show_info(self, todo_id: int) -> None:
        todo = await self.client.get(todo_id)
        if not todo:
            return
        title = f"#{todo.id} {todo.text}"
        body = todo.desc or "(no description)"
        result = await self.push_screen_wait(InfoScreen(title, body))
        if result == "dispatch":
            self.run_worker(self._dispatch_claude(todo_id))

    async def action_show_info(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        self.run_worker(self._show_info(todo_id))

    async def _dispatch_claude(self, todo_id: int) -> None:
        if todo_id in self._bot_running:
            self.notify("Already running", severity="warning")
            return
        todo = await self.client.get(todo_id)
        if not todo:
            return
        if todo.desc:
            prompt = f"Todo: {todo.text}\n\nDescription:\n{todo.desc}"
        else:
            prompt = f"Todo: {todo.text}"
        self._bot_running.add(todo_id)
        await self._update_labels()
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                response = stdout.decode().strip()
                fresh = await self.client.get(todo_id)
                if fresh:
                    new_desc = (fresh.desc or "") + BOT_DIVIDER + response
                    await self.client.update_desc(todo_id, new_desc)
                self.notify(f"Bot replied on #{todo_id}")
            else:
                err = stderr.decode()[:100]
                self.notify(f"Claude error: {err}", severity="error")
        except FileNotFoundError:
            self.notify("claude CLI not found", severity="error")
        finally:
            self._bot_running.discard(todo_id)
            await self._update_labels()

    async def _delete_todo(self, todo_id: int) -> None:
        todo = await self.client.get(todo_id)
        if not todo:
            return
        desc_count = len(await self.client.get_descendants(todo_id))
        if desc_count > 0:
            msg = f'Delete "#{todo_id} {todo.text}" and {desc_count} subtask(s)? (y/n)'
        else:
            msg = f'Delete "#{todo_id} {todo.text}"? (y/n)'
        confirmed = await self.push_screen_wait(ConfirmScreen(msg))
        if confirmed:
            parent_id = todo.parent
            if parent_id:
                siblings = await self.client.get_children(parent_id)
            else:
                siblings = [t for t in await self.client.list_active() if t.parent is None]
            sibling_id = next((s.id for s in siblings if s.id != todo_id), None)
            select_id = sibling_id or parent_id
            await self.client.delete(todo_id)
            await self._refresh_tree(select_id=select_id)

    async def action_delete_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        self.run_worker(self._delete_todo(todo_id))

    async def action_cycle_filter(self) -> None:
        self._filter_mode = (self._filter_mode + 1) % 2
        self._update_header()
        self._save_ui_state()
        await self._refresh_tree()

    async def action_refresh(self) -> None:
        await self._refresh_tree(select_id=self._get_selected_todo_id())

    def action_toggle_theme(self) -> None:
        try:
            idx = self._THEMES.index(self.theme)
        except ValueError:
            idx = -1
        self.theme = self._THEMES[(idx + 1) % len(self._THEMES)]
        self._update_header()
        self._save_ui_state()
        self.notify(f"Theme: {self.theme}")

    async def action_toggle_stale(self) -> None:
        self._hide_stale = not self._hide_stale
        self._update_header()
        await self._refresh_tree()

    # ── pomodoro ──

    async def _pomodoro_tick(self) -> None:
        transition = self._pomodoro.tick()
        bar = self.query_one(PomodoroBar)
        bar.refresh_display(self._pomodoro)
        if transition is not None:
            if self.client.pomodoro:
                try:
                    await self.client.pomodoro.record_session(
                        started_at=transition.started_at,
                        finished_at=transition.finished_at,
                        phase=transition.finished_phase.value,
                        duration_seconds=transition.duration_seconds,
                        completed=transition.completed,
                    )
                except TodoClientError:
                    pass
            self._send_pomodoro_notification(transition)
            self.run_worker(self._pomodoro_complete(transition))

    async def _pomodoro_complete(self, transition: PhaseTransition) -> None:
        title = {
            Phase.FOCUS: "Focus session complete!",
            Phase.BREAK: "Break is over!",
            Phase.LONG_BREAK: "Long break is over!",
        }
        body = {
            Phase.FOCUS: "Time to focus",
            Phase.BREAK: "Take a short break",
            Phase.LONG_BREAK: "Take a long break",
        }
        await self.push_screen_wait(InfoScreen(
            title.get(transition.finished_phase, "Pomodoro"),
            body.get(transition.next_phase, ""),
        ))
        bar = self.query_one(PomodoroBar)
        bar.flash()

    def _send_pomodoro_notification(self, transition: PhaseTransition) -> None:
        phase_labels = {
            Phase.FOCUS: "Focus session complete!",
            Phase.BREAK: "Break is over!",
            Phase.LONG_BREAK: "Long break is over!",
        }
        next_labels = {
            Phase.FOCUS: "Time to focus",
            Phase.BREAK: "Take a short break",
            Phase.LONG_BREAK: "Take a long break",
        }
        title = phase_labels.get(transition.finished_phase, "Pomodoro")
        body = next_labels.get(transition.next_phase, "")
        try:
            if platform.system() == "Darwin":
                subprocess.run(
                    ["osascript", "-e",
                     f'display notification "{body}" with title "{title}" sound name "Glass"'],
                    timeout=5,
                    capture_output=True,
                )
            else:
                subprocess.run(
                    ["notify-send", title, body],
                    timeout=5,
                    capture_output=True,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    async def _pomodoro_menu(self) -> None:
        action = await self.push_screen_wait(
            PomodoroMenuScreen(self._pomodoro.state)
        )
        if not action:
            return
        if action == "start":
            self._pomodoro.start()
        elif action == "pause":
            self._pomodoro.pause()
        elif action == "resume":
            self._pomodoro.resume()
        elif action == "skip":
            transition = self._pomodoro.skip()
            if transition:
                try:
                    await self.client.pomodoro.record_session(
                        started_at=transition.started_at,
                        finished_at=transition.finished_at,
                        phase=transition.finished_phase.value,
                        duration_seconds=transition.duration_seconds,
                        completed=transition.completed,
                    )
                except TodoClientError:
                    pass
                self._send_pomodoro_notification(transition)
        elif action == "reset":
            self._pomodoro.reset()
        elif action == "history":
            await self._show_pomodoro_history()
            return
        bar = self.query_one(PomodoroBar)
        bar.refresh_display(self._pomodoro)

    async def _show_pomodoro_history(self) -> None:
        try:
            sessions = await self.client.pomodoro.today_sessions()
        except TodoClientError:
            self.notify("Failed to load pomodoro history", severity="error")
            return
        if not sessions:
            self.notify("No pomodoro sessions today", severity="warning")
            return
        focus_done = sum(1 for s in sessions if s.phase == "focus" and s.completed)
        focus_skipped = sum(1 for s in sessions if s.phase == "focus" and not s.completed)
        total_focus_min = sum(s.duration_seconds for s in sessions if s.phase == "focus" and s.completed) // 60
        lines = [f"Today: {focus_done} focus completed, {focus_skipped} skipped, {total_focus_min} min total", ""]
        for s in sessions:
            phase_label = {"focus": "FOCUS", "break": "BREAK", "long_break": "LONG BREAK"}.get(s.phase, s.phase)
            t = s.started_at[11:16]  # HH:MM
            mins = s.duration_seconds // 60
            status = "\u2713" if s.completed else "skip"
            lines.append(f"  {t}  {phase_label:<12} {mins}min  {status}")
        body = "\n".join(lines)
        await self.push_screen_wait(InfoScreen("\U0001f345 Pomodoro History", body))

    async def action_pomodoro_menu(self) -> None:
        self.run_worker(self._pomodoro_menu())


def run_tui(
    remote_url: str | None = None,
    remote_token: str | None = None,
    db_path: str | None = None,
    pomo_durations: dict[Phase, int] | None = None,
) -> None:
    """TUI entry point. Textual manages the event loop."""
    from .client import TodoClient
    from .server.runner import start_embedded_server

    if remote_url:
        base_url = remote_url
        token = remote_token or ""
    else:
        base_url, token = start_embedded_server(db_path=db_path)

    client = TodoClient(base_url, api_token=token if token else None)
    app = TodoApp(client, pomo_durations=pomo_durations)
    try:
        app.run()
    finally:
        pass
