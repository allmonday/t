from __future__ import annotations

import os
import pickle
from datetime import datetime, timedelta

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, Static, Tree
from textual.widgets.tree import TreeNode

from .models import Todo
from .store import TodoStore
from .tree import build_children_map, format_time


# ── helpers ──


class TodoTree(Tree[int]):
    """Tree subclass that aligns leaf nodes with expandable nodes."""

    guide_depth = 4
    show_root = True

    def render_label(self, node, base_style, style):
        node_label = node._label.copy()
        node_label.stylize(style)
        if node == self.cursor_node:
            return Text.assemble(("● ", "bold"), node_label)
        else:
            return Text.assemble(("  ", base_style), node_label)


def _render_label(todo: Todo, is_leaf: bool = True) -> Text:
    time = format_time(todo.created)
    text = Text()
    if todo.done:
        text.append(todo.text, style="strike dim")
    elif not is_leaf:
        text.append(todo.text, style="dim")
    else:
        text.append(todo.text)
    text.append(f"  #{todo.id}", style="dim")
    text.append(f"  {time}", style="dim italic" if not todo.done else "strike dim")
    if todo.done_at:
        text.append(f"  done {format_time(todo.done_at)}", style="green dim italic")
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
    CSS = """
    Screen {
        layout: vertical;
    }
    TodoTree {
        height: 1fr;
        margin: 0 0 0 1;
    }
    TodoTree > .tree--cursor {
        background: transparent;
        text-style: none;
    }
    TodoTree > .tree--highlight {
        background: transparent;
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
        Binding("a", "add_root", "Add"),
        Binding("tab", "add_child", "Sub-task", priority=True),
        Binding("d", "delete_todo", "Delete"),
        Binding("e", "edit_todo", "Edit"),
        Binding("space", "toggle_todo", "Toggle", priority=True),
        Binding("h", "collapse_node", "Collapse", priority=True),
        Binding("left", "collapse_node", "Collapse", show=False, priority=True),
        Binding("l", "expand_node", "Expand", priority=True),
        Binding("right", "expand_node", "Expand", show=False, priority=True),
        Binding("m", "toggle_all", "Fold/Unfold All", priority=True),
        Binding("f", "cycle_filter", "Filter"),
        Binding("S", "toggle_stale", "Stale"),
        Binding("T", "toggle_theme", "Theme"),
        Binding("q", "quit", "Quit"),
    ]

    _UI_STATE_PATH = os.path.expanduser("~/.todo_ui_state.pkl")
    _THEMES = [
        "textual-dark",
        "textual-light",
        "nord",
        "gruvbox",
        "catppuccin-mocha",
        "catppuccin-latte",
        "dracula",
        "tokyo-night",
        "solarized-light",
        "solarized-dark",
    ]

    def __init__(self, store: TodoStore) -> None:
        super().__init__()
        self.store = store
        self._filter_mode: int = 0  # 0=All, 1=Pending, 2=Done
        self._filter_labels = ["All", "Pending", "Done"]
        self._filter_values: list[bool | None] = [None, False, True]
        self._hide_stale: bool = True
        self._g_pending: bool = False
        ui_state = self._load_ui_state()
        self._saved_expanded: set[int] = ui_state.get("expanded", set())
        self._saved_theme: str = ui_state.get("theme", self._THEMES[0])

    def compose(self) -> ComposeResult:
        yield Header()
        yield TodoTree("TODO")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = self._saved_theme
        self._update_header()
        self._refresh_tree(force_expand=self._saved_expanded)

    def _update_header(self) -> None:
        self.title = "TODO"
        label = self._filter_labels[self._filter_mode]
        stale_label = "hidden" if self._hide_stale else "shown"
        self.sub_title = f"Filter: {label}  |  Stale: {stale_label}"
        self.query_one("#status-bar", Static).update(f"Theme: {self.theme}")

    def _load_ui_state(self) -> dict:
        try:
            with open(self._UI_STATE_PATH, "rb") as f:
                data = pickle.load(f)
            # 兼容旧格式（set）
            if isinstance(data, set):
                return {"expanded": data, "theme": self._THEMES[0]}
            return data
        except (FileNotFoundError, EOFError, pickle.UnpicklingError):
            return {"expanded": set(), "theme": self._THEMES[0]}

    def _save_ui_state(self) -> None:
        tree = self.query_one(TodoTree)
        expanded_ids: set[int] = set()
        for node in tree.root.children:
            self._collect_expanded(node, expanded_ids)
        state = {"expanded": expanded_ids, "theme": self.theme}
        with open(self._UI_STATE_PATH, "wb") as f:
            pickle.dump(state, f)

    def action_quit(self) -> None:
        self._save_ui_state()
        self.exit()

    # ── tree building ──

    def _refresh_tree(self, select_id: int | None = None, force_expand: set[int] | None = None) -> None:
        tree = self.query_one(TodoTree)

        # 保存当前展开状态
        expanded_ids: set[int] = set()
        for node in tree.root.children:
            self._collect_expanded(node, expanded_ids)
        if force_expand:
            expanded_ids |= force_expand

        tree.clear()

        filter_done = self._filter_values[self._filter_mode]
        todos = self.store.list_active()

        # filter by root done status
        if filter_done is not None:
            children_map = build_children_map(todos)
            root_ids = {t.id for t in children_map.get(None, []) if t.done == filter_done}
            keep_ids: set[int] = set()

            def collect_ids(tid: int) -> None:
                keep_ids.add(tid)
                for child in children_map.get(tid, []):
                    collect_ids(child.id)

            for rid in root_ids:
                collect_ids(rid)
            todos = [t for t in todos if t.id in keep_ids]

        # hide stale: done root todos completed over 2 days ago
        if self._hide_stale:
            cutoff = (datetime.now() - timedelta(days=2)).isoformat()
            children_map = build_children_map(todos)
            stale_root_ids = {
                t.id for t in children_map.get(None, [])
                if t.done and t.done_at and t.done_at < cutoff
            }
            if stale_root_ids:
                remove_ids: set[int] = set()

                def collect_stale(tid: int) -> None:
                    remove_ids.add(tid)
                    for child in children_map.get(tid, []):
                        collect_stale(child.id)

                for rid in stale_root_ids:
                    collect_stale(rid)
                todos = [t for t in todos if t.id not in remove_ids]

        children_map = build_children_map(todos)
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
            # 确保祖先链展开，否则 select_node 无效
            parent = node.parent
            while parent is not None:
                parent.expand()
                parent = parent.parent
            tree.select_node(node)

        tree.root.expand()

    @staticmethod
    def _collect_expanded(node: TreeNode[int], expanded_ids: set[int]) -> None:
        if node.data is not None and node.is_expanded:
            expanded_ids.add(node.data)
        for child in node.children:
            TodoApp._collect_expanded(child, expanded_ids)

    def _update_labels(self) -> None:
        """就地更新所有节点标签，不重建树，光标位置不变。"""
        tree = self.query_one(TodoTree)
        todos = {t.id: t for t in self.store.list_active()}

        def walk(node: TreeNode[int]) -> None:
            if node.data is not None and node.data in todos:
                node.set_label(_render_label(todos[node.data]))
            for child in node.children:
                walk(child)

        walk(tree.root)
        # 更新标题计数
        filter_done = self._filter_values[self._filter_mode]
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

    def action_toggle_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        if self.store.has_children(todo_id):
            return  # 父节点不可 toggle，用 h/l 折叠展开
        self.store.toggle(todo_id)
        # 只更新受影响节点的标签，不重建整棵树
        self._update_labels()

    def action_collapse_node(self) -> None:
        tree = self.query_one(TodoTree)
        node = tree.cursor_node
        if node and node.is_expanded:
            node.collapse()

    def action_expand_node(self) -> None:
        tree = self.query_one(TodoTree)
        node = tree.cursor_node
        if node and not node.is_expanded:
            node.expand()  # 只展开当前一层，子节点保持原状

    def action_toggle_all(self) -> None:
        tree = self.query_one(TodoTree)
        # 检查是否有任何节点展开，有则全部收起，否则全部展开
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

    def action_add_root(self) -> None:
        def on_input(text: str) -> None:
            if text:
                todo = self.store.add(text)
                self._refresh_tree(select_id=todo.id)

        self.push_screen(InputScreen("New root todo"), callback=on_input)

    def action_add_child(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            self.action_add_root()
            return

        def on_input(text: str) -> None:
            if text:
                new_todo = self.store.add(text, parent_id=todo_id)
                # 直接在当前节点下插入，不重建整棵树
                tree = self.query_one(TodoTree)
                node = tree.cursor_node
                if node is not None:
                    label = _render_label(new_todo)
                    node.add_leaf(label, data=new_todo.id)
                    node.expand()
                    # 更新父节点标签（可能从叶子变成了分支）
                    parent_todo = self.store.get(todo_id)
                    if parent_todo:
                        node.set_label(_render_label(parent_todo))

        todo = self.store.get(todo_id)
        prompt = f"Sub-task of #{todo_id}" + (f" ({todo.text[:20]})" if todo else "")
        self.push_screen(InputScreen(prompt), callback=on_input)

    def action_edit_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        todo = self.store.get(todo_id)
        if not todo:
            return

        def on_edit(text: str) -> None:
            if text and text != todo.text:
                self.store.update_text(todo_id, text)
                self._update_labels()

        self.push_screen(InputScreen(f"Edit #{todo_id}", default=todo.text), callback=on_edit)

    def action_delete_todo(self) -> None:
        todo_id = self._get_selected_todo_id()
        if todo_id is None:
            return
        todo = self.store.get(todo_id)
        if not todo:
            return
        desc_count = len(self.store.get_descendants(todo_id))
        if desc_count > 0:
            msg = f'Delete "#{todo_id} {todo.text}" and {desc_count} subtask(s)? (y/n)'
        else:
            msg = f'Delete "#{todo_id} {todo.text}"? (y/n)'

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self.store.delete(todo_id)
                self._refresh_tree()

        self.push_screen(ConfirmScreen(msg), callback=on_confirm)

    def action_cycle_filter(self) -> None:
        self._filter_mode = (self._filter_mode + 1) % 3
        self._update_header()
        self._refresh_tree()

    def action_toggle_theme(self) -> None:
        try:
            idx = self._THEMES.index(self.theme)
        except ValueError:
            idx = -1
        self.theme = self._THEMES[(idx + 1) % len(self._THEMES)]
        self._update_header()
        self._save_ui_state()

    def action_toggle_stale(self) -> None:
        self._hide_stale = not self._hide_stale
        self._update_header()
        self._refresh_tree()


def run_tui(store: TodoStore) -> None:
    app = TodoApp(store)
    app.run()
