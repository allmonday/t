from __future__ import annotations

import argparse
import asyncio
import os
import sys


def _load_config() -> dict:
    path = os.path.expanduser("~/.todoiumrc")
    if not os.path.isfile(path):
        return {}
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
    return config


def _get_remote_config(args_url=None, args_token=None):
    cfg = _load_config()
    url = args_url or os.environ.get("TODO_REMOTE_URL") or cfg.get("remote")
    token = args_token or os.environ.get("TODO_REMOTE_TOKEN") or cfg.get("token")
    return url, token


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
    parser.add_argument("--remote", type=str, metavar="URL", help="Remote server URL")
    parser.add_argument("--token", type=str, metavar="TOKEN", help="API token for remote server")
    parser.add_argument("--token_env", type=str, metavar="ENV_VAR", help="Read API token from this environment variable")
    parser.add_argument("--server", action="store_true", help="Start standalone HTTP server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Server bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Server bind port (default: 8000)")
    parser.add_argument("--db", type=str, default=None, help="Database path (default: ~/.todo.db)")

    args = parser.parse_args()

    # ── server mode ──
    if args.server:
        token = args.token or (os.environ.get(args.token_env) if args.token_env else None)
        if not token:
            print("Error: --token or --token_env is required when running as server", file=sys.stderr)
            sys.exit(1)
        import uvicorn
        from .server.app import create_app
        app, _ = create_app(db_path=args.db, api_token=token)
        uvicorn.run(app, host=args.host, port=args.port)
        return

    remote_url, remote_token = _get_remote_config(
        args.remote,
        args.token or (os.environ.get(args.token_env) if args.token_env else None),
    )
    if remote_url and not remote_url.startswith("https://"):
        print(f"Warning: remote URL is not HTTPS: {remote_url}", file=sys.stderr)

    # Build pomodoro durations from config
    cfg = _load_config()
    pomo_durations = None
    pomo_focus = cfg.get("pomo_focus")
    pomo_break = cfg.get("pomo_break")
    pomo_long_break = cfg.get("pomo_long_break")
    if pomo_focus or pomo_break or pomo_long_break:
        from .pomodoro import DEFAULT_DURATIONS, Phase
        pomo_durations = dict(DEFAULT_DURATIONS)
        if pomo_focus:
            pomo_durations[Phase.FOCUS] = int(pomo_focus) * 60
        if pomo_break:
            pomo_durations[Phase.BREAK] = int(pomo_break) * 60
        if pomo_long_break:
            pomo_durations[Phase.LONG_BREAK] = int(pomo_long_break) * 60

    if not args.text and not args.list and args.toggle is None and args.desc is None:
        # TUI mode
        from .tui import run_tui
        try:
            run_tui(remote_url=remote_url, remote_token=remote_token, db_path=args.db, pomo_durations=pomo_durations)
        except KeyboardInterrupt:
            pass
        return

    # CLI mode
    from .cli import CliError, console

    async def async_main():
        from .client import TodoClient
        from .server.runner import start_embedded_server

        if remote_url:
            base_url = remote_url
            token = remote_token or ""
        else:
            base_url, token = start_embedded_server(db_path=args.db)

        client = TodoClient(base_url, api_token=token if token else None)
        try:
            if args.text:
                from .cli import cli_add
                await cli_add(client, " ".join(args.text), args.parent)
            elif args.list:
                from .cli import cli_list
                filter_done = True if args.done else (False if args.pending else None)
                await cli_list(client, filter_done=filter_done)
            elif args.toggle is not None:
                from .cli import cli_toggle
                await cli_toggle(client, args.toggle)
            elif args.desc is not None:
                if not args.message:
                    console.print("[red]--desc requires -m <description text>[/red]")
                    sys.exit(1)
                from .cli import cli_desc
                await cli_desc(client, args.desc, args.message)
        finally:
            await client.close()

    try:
        asyncio.run(async_main())
    except CliError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(e.exit_code)
