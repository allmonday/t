"""Start FastAPI server in a background thread (local/embedded mode)."""
from __future__ import annotations

import socket
import threading
import time

import httpx
import uvicorn

from .app import create_app


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_embedded_server(
    db_path: str | None = None,
    api_token: str | None = None,
    port: int | None = None,
) -> tuple[str, str]:
    """Start FastAPI server in a daemon thread.

    Returns:
        (base_url, token) for client to connect.
    """
    if port is None:
        port = find_free_port()

    app, token = create_app(db_path=db_path, api_token=api_token)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    _wait_for_server(base_url, token)
    return base_url, token


def _wait_for_server(base_url: str, token: str, timeout: float = 10) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/health", headers=headers, timeout=1)
            if r.status_code == 200:
                return
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.1)
    raise RuntimeError("Embedded server failed to start within timeout")
