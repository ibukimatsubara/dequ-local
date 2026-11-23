"""Shared test values and how to start a real server."""

import socket
import threading
import time
from contextlib import contextmanager

import uvicorn

from dequ.app import create_app
from dequ.config import Settings

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CARD = {
    "agent": {"kind": "claude", "name": "Claude Code", "where": "laptop"},
    "task": "Add Google sign-in to the login screen.",
    "progress": "The button and the redirect handling are done.",
    "blocked": "The app name for the consent screen is not decided.",
    "question": "Which app name on the consent screen?",
    "options": [
        {"id": "product", "label": "Use the product name", "effect": "Clear to users."},
        {"id": "company", "label": "Use the company name", "effect": "Reusable."},
    ],
    "recommended": "product",
    "reason": "Users see what they are granting access to.",
}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def serving(app):
    """Run an ASGI app on a free local port for the duration of the block."""
    port = free_port()
    instance = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not instance.started:
        assert time.monotonic() < deadline, "the server did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        instance.should_exit = True
        thread.join(timeout=10)


@contextmanager
def running_server(data_dir):
    with serving(create_app(Settings(token=TOKEN, data_dir=data_dir))) as url:
        yield url
