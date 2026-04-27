from __future__ import annotations

from rich.console import Console
from rich.text import Text
from rich.tree import Tree

from .models import Todo
from .store import TodoStore
from .tree import build_children_map, filter_by_roots, format_time

console = Console()


def _render_node(todo: Todo) -> Text:
    mark = "[✓]" if todo.done else "[ ]"
    time = format_time(todo.created)
    text = Text()
    text.append(f"{mark} ", style="green" if todo.done else "dim")
    text.append(f"#{todo.id}  ", style="cyan" if not todo.done else "strike dim cyan")
    if todo.done:
        text.append(todo.text, style="strike dim")
    else:
        text.append(todo.text)
    text.append(f"  {time}", style="dim" if not todo.done else "strike dim")
    return text


def _build_rich_tree(parent_tree: Tree, parent_id: int, children_map: dict[int | None, list[Todo]]) -> None:
    for child in children_map.get(parent_id, []):
        label = _render_node(child)
        branch = parent_tree.add(label)
        _build_rich_tree(branch, child.id, children_map)


def cli_list(store: TodoStore, filter_done: bool | None = None) -> None:
    todos = store.list_active()
    todos = filter_by_roots(todos, filter_done)
    if not todos:
        label = "pending" if filter_done is False else ("done" if filter_done else "")
        console.print(f"[dim]No {label} todos found.[/dim]")
        return
    children_map = build_children_map(todos)
    roots = children_map.get(None, [])
    count = len(todos)
    suffix = ""
    if filter_done is True:
        suffix = " done"
    elif filter_done is False:
        suffix = " pending"
    tree = Tree(f"[bold cyan]TODO[/bold cyan] ({count} items{suffix})")
    for root in roots:
        label = _render_node(root)
        branch = tree.add(label)
        _build_rich_tree(branch, root.id, children_map)
    console.print(tree)


def cli_add(store: TodoStore, text: str, parent_id: int | None = None) -> None:
    if not text.strip():
        console.print("[red]Task text cannot be empty.[/red]")
        raise SystemExit(1)
    try:
        todo = store.add(text.strip(), parent_id)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)
    parent_info = f" (under #{parent_id})" if parent_id else ""
    console.print(f"[green]Added[/green] [cyan]#{todo.id}[/cyan]: {todo.text}{parent_info}")


def cli_toggle(store: TodoStore, todo_id: int) -> None:
    todo = store.get(todo_id)
    if not todo:
        console.print(f"[red]Todo #{todo_id} not found.[/red]")
        raise SystemExit(1)
    if store.has_children(todo_id):
        console.print(f"[red]#{todo_id} has subtasks — complete them instead.[/red]")
        raise SystemExit(1)
    store.toggle(todo_id)
    updated = store.get(todo_id)
    if updated and updated.done:
        console.print(f"[green]Done[/green] [strike dim]#{todo_id}: {updated.text}[/strike dim]")
    elif updated:
        console.print(f"[yellow]Undone[/yellow] [cyan]#{todo_id}[/cyan]: {updated.text}")
