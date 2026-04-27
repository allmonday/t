from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="todo", description="Todo manager with tree support")
    parser.add_argument("text", nargs="*", help="Todo text to add (e.g. t buy milk)")
    parser.add_argument("-p", "--parent", type=int, metavar="ID", help="Parent todo ID")
    parser.add_argument("-l", "--list", action="store_true", help="List all todos")
    parser.add_argument("-x", "--toggle", type=int, metavar="ID", help="Toggle todo done status")
    parser.add_argument("--done", action="store_true", help="Filter: show only done root tasks")
    parser.add_argument("--pending", action="store_true", help="Filter: show only pending root tasks")

    args = parser.parse_args()

    from .store import TodoStore

    store = TodoStore()
    store.connect()

    try:
        if args.text:
            from .cli import cli_add
            cli_add(store, " ".join(args.text), args.parent)
        elif args.list:
            from .cli import cli_list
            filter_done = True if args.done else (False if args.pending else None)
            cli_list(store, filter_done=filter_done)
        elif args.toggle is not None:
            from .cli import cli_toggle
            cli_toggle(store, args.toggle)
        else:
            from .tui import run_tui
            run_tui(store)
    finally:
        store.close()
