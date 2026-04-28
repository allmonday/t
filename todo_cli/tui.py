from __future__ import annotations

import json
import os

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Static, Tree
from textual.widgets.tree import TreeNode

from .models import TodoEntity
from .store import TodoStore
from .tree import build_children_map, filter_todos, format_time


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
        if node._allow_expand:
            icon = self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE
            text = Text.assemble((icon, base_style), node_label)
        else:
            text = Text.assemble(("", base_style), node_label)
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


def _render_label(todo: TodoEntity, is_leaf: bool = True) -> Text:
    time = format_time(todo.created)
    if todo.done:
        text = Text(style="dim")
        text.append(f"#{todo.id} ")
        text.append(todo.text, style="strike")
        if time:
            text.append(f"  {time}", style="italic")
        if todo.done_at:
            done_time = format_time(todo.done_at)
            if done_time:
                text.append(f"  {done_time}", style="green italic")
    else:
        text = Text()
        text.append(f"#{todo.id} ", style="dim")
        text.append(todo.text)
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
        Binding("space", "toggle_todo", "Toggle", priority=True),
        Binding("h", "press_h", "Collapse", priority=True),
        Binding("left", "collapse_node", "Collapse", show=False, priority=True),
        Binding("l", "press_l", "Expand", priority=True),
        Binding("right", "expand_node", "Expand", show=False, priority=True),
        Binding("m", "toggle_all", "Fold/Unfold All", priority=True),
        Binding("f", "cycle_filter", "Filter"),
        Binding("S", "toggle_stale", "Stale"),
        Binding("T", "toggle_theme", "Theme"),
        Binding("q", "quit", "Quit"),
    ]

    _UI_STATE_PATH = os.path.expanduser("~/.todo_ui_state.json")
    _THEMES = [
        "gruvbox",
        "dracula",
        "textual-dark",
        "nord",
    ]

    def __init__(self, store: TodoStore, engine=None) -> None:
        super().__init__()
        self.store = store
        self._engine = engine
        self._filter_mode: int = 0  # 0=All, 1=Pending, 2=Done
        self._filter_labels = ["All", "Pending", "Done"]
        self._filter_values: list[bool | None] = [None, False, True]
        self._hide_stale: bool = True
        self._g_pending: bool = False
        self._l_pending: bool = False
        self._h_pending: bool = False
        ui_state = self._load_ui_state()
        self._saved_expanded: set[int] = ui_state.get("expanded", set())
        self._saved_theme: str = ui_state.get("theme", self._THEMES[0])

    def compose(self) -> ComposeResult:
        yield Header()
        yield TodoTree("TODO")
        yield Static("", id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        self.theme = self._saved_theme
        self._update_header()
        await self._refresh_tree(force_expand=self._saved_expanded)

    def _update_header(self) -> None:
        self.title = "TODO"
        label = self._filter_labels[self._filter_mode]
        stale_label = "hidden" if self._hide_stale else "shown"
        self.sub_title = f"Filter: {label}  |  Stale: {stale_label}"
        self.query_one("#status-bar", Static).update(f"Theme: {self.theme}")

    def _load_ui_state(self) -> dict:
        try:
            with open(self._UI_STATE_PATH, "r") as f:
                data = json.load(f)
            return {
                "expanded": set(data.get("expanded", [])),
                "theme": data.get("theme", self._THEMES[0]),
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
        state = {"expanded": sorted(expanded_ids), "theme": self.theme}
        with open(self._UI_STATE_PATH, "w") as f:
            json.dump(state, f)

    def action_quit(self) -> None:
        self._save_ui_state()
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
        todos = await self.store.list_active()
        todos = filter_todos(todos, filter_done=filter_done, hide_stale=self._hide_stale)
        children_map = build_children_map(todos)

        tree.clear()
        count = len(todos)
        suffix = f" {self._filter_labels[self._filter_mode].lower()}" if self._filter_mode else ""
        tree.root.set_label(f"[bold cyan]TODO[/bold cyan] ({count} items{suffix})")
        tree.root.expand()

        node_map: dict[int, TreeNode[int]] = {}

        def add_nodes(parent_node: TreeNode[int], parent_id: int | None) -> None:
            for todo in children_map.get(parent_id, []):
                has_children = todo.id in children_map
                label = _render_label(todo, is_leaf=not has_children)
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
            parent = node.parent
            while parent is not None:
                parent.expand()
                parent = parent.parent
            tree.root.expand()

            def _restore_cursor(n=node):
                tree.select_node(n)
                tree.scroll_to_node(n)

            self.call_after_refresh(_restore_cursor)
        else:
            tree.root.expand()

    @staticmethod
    def _collect_expanded(node: TreeNode[int], expanded_ids: set[int]) -> None:
        if node.data is not None and node.is_expanded:
            expanded_ids.add(node.data)
        for child in node.children:
            TodoApp._collect_expanded(child, expanded_ids)

    async def _update_labels(self) -> None:
        """就地更新所有节点标签，不重建树，光标位置不变。仅用于 edit 场景。"""
        tree = self.query_one(TodoTree)
        todos = {t.id: t for t in await self.store.list_active()}

        def walk(node: TreeNode[int]) -> None:
            if node.data is not None and node.data in todos:
                is_leaf = not bool(node.children)
                node.set_label(_render_label(todos[node.data], is_leaf=is_leaf))
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

    async def action_toggle_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        if await self.store.has_children(todo_id):
            self.notify("Has sub-tasks, toggle leaves only", severity="warning")
            return
        await self.store.toggle(todo_id)
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
        todo = await self.store.get(todo_id)
        if not todo:
            return
        parent_id = todo.parent

        if parent_id:
            parent = await self.store.get(parent_id)
            prompt = f"Sibling of #{todo_id}" + (f" (under {parent.text[:20]})" if parent else "")
        else:
            prompt = "New root todo"
        text = await self.push_screen_wait(InputScreen(prompt))
        if text:
            new_todo = await self.store.add(text, parent_id=parent_id)
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
            todo = await self.store.add(text)
            await self._refresh_tree(select_id=todo.id)

    async def action_add_root(self) -> None:
        self.run_worker(self._add_root())

    async def _add_child(self, todo_id: int) -> None:
        todo = await self.store.get(todo_id)
        prompt = f"Sub-task of #{todo_id}" + (f" ({todo.text[:20]})" if todo else "")
        text = await self.push_screen_wait(InputScreen(prompt))
        if text:
            new_todo = await self.store.add(text, parent_id=todo_id)
            await self._refresh_tree(select_id=new_todo.id, force_expand={todo_id})

    async def action_add_child(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            self.run_worker(self._add_root())
        else:
            self.run_worker(self._add_child(todo_id))

    async def _edit_todo(self, todo_id: int) -> None:
        todo = await self.store.get(todo_id)
        if not todo:
            return
        new_text = await self.push_screen_wait(InputScreen(f"Edit #{todo_id} text", default=todo.text))
        if new_text and new_text != todo.text:
            await self.store.update_text(todo_id, new_text)
        new_desc = await self.push_screen_wait(InputScreen(f"Edit #{todo_id} desc", default=todo.desc or ""))
        if new_desc and new_desc != (todo.desc or ""):
            await self.store.update_desc(todo_id, new_desc)
        await self._update_labels()

    async def action_edit_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        self.run_worker(self._edit_todo(todo_id))

    async def _delete_todo(self, todo_id: int) -> None:
        todo = await self.store.get(todo_id)
        if not todo:
            return
        desc_count = len(await self.store.get_descendants(todo_id))
        if desc_count > 0:
            msg = f'Delete "#{todo_id} {todo.text}" and {desc_count} subtask(s)? (y/n)'
        else:
            msg = f'Delete "#{todo_id} {todo.text}"? (y/n)'
        confirmed = await self.push_screen_wait(ConfirmScreen(msg))
        if confirmed:
            parent_id = todo.parent
            if parent_id:
                siblings = await self.store.get_children(parent_id)
            else:
                siblings = [t for t in await self.store.list_active() if t.parent is None]
            sibling_id = next((s.id for s in siblings if s.id != todo_id), None)
            select_id = sibling_id or parent_id
            await self.store.delete(todo_id)
            await self._refresh_tree(select_id=select_id)

    async def action_delete_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        self.run_worker(self._delete_todo(todo_id))

    async def action_cycle_filter(self) -> None:
        self._filter_mode = (self._filter_mode + 1) % 3
        self._update_header()
        await self._refresh_tree()

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


def run_tui() -> None:
    """TUI 入口，Textual 自管理 event loop。"""
    import asyncio

    from .db import create_engine_and_session, init_db, seed_if_empty
    from .store import TodoStore

    async def setup():
        engine, session_factory = create_engine_and_session()
        await init_db(engine)
        await seed_if_empty(session_factory)
        return engine, session_factory

    engine, session_factory = asyncio.run(setup())
    store = TodoStore(session_factory)
    app = TodoApp(store, engine)
    app.run()
