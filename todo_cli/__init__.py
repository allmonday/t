from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="todo", description="Todo manager with tree support")
    parser.add_argument("text", nargs="*", help="Todo text to add (e.g. t buy milk)")
    parser.add_argument("-p", "--parent", type=int, metavar="ID", help="Parent todo ID")
    parser.add_argument("-l", "--list", action="store_true", help="List all todos")
    parser.add_argument("-x", "--toggle", type=int, metavar="ID", help="Toggle todo done status")
    parser.add_argument("--desc", type=int, metavar="ID", help="Set description for a todo (use with -m)")
    parser.add_argument("-m", "--message", type=str, metavar="TEXT", help="Description text (use with --desc)")
    parser.add_argument("--done", action="store_true", help="Filter: show only done root tasks")
    parser.add_argument("--pending", action="store_true", help="Filter: show only pending root tasks")

    args = parser.parse_args()

    if not args.text and not args.list and args.toggle is None and args.desc is None:
        # TUI 模式 — Textual 自管理 event loop
        from .tui import run_tui
        try:
            run_tui()
        except KeyboardInterrupt:
            pass
        return

    # CLI 模式 — 用 asyncio.run() 桥接
    from .cli import CliError, console

    async def async_main():
        from .db import create_engine_and_session, init_db, seed_if_empty
        from .store import TodoStore

        engine, session_factory = create_engine_and_session()
        await init_db(engine)
        await seed_if_empty(session_factory)
        store = TodoStore(session_factory)

        try:
            if args.text:
                from .cli import cli_add
                await cli_add(store, " ".join(args.text), args.parent)
            elif args.list:
                from .cli import cli_list
                filter_done = True if args.done else (False if args.pending else None)
                await cli_list(store, filter_done=filter_done)
            elif args.toggle is not None:
                from .cli import cli_toggle
                await cli_toggle(store, args.toggle)
            elif args.desc is not None:
                if not args.message:
                    console.print("[red]--desc requires -m <description text>[/red]")
                    sys.exit(1)
                from .cli import cli_desc
                await cli_desc(store, args.desc, args.message)
        finally:
            await engine.dispose()

    try:
        asyncio.run(async_main())
    except CliError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(e.exit_code)
