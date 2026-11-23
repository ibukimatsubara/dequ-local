"""The dequ command. Starts the server and waits for answers."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn

from .app import card_ids, create_app, is_loopback_host
from .config import load_settings
from .store import FirestoreBell

# The server holds wait=50 for up to 50 seconds. A shorter timeout cuts off just before an answer and causes a retry.
_REQUEST_TIMEOUT = 70
_RETRY_SECONDS = 5
_FIRESTORE_TARGET_ID = 1


def _serve(config: Path | None, host: str, port: int) -> int:
    try:
        settings = load_settings(config, os.environ)
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    if settings.token is None and not is_loopback_host(host):
        print(
            f"DEQU_TOKEN is not set; without a token DeQu listens only on this computer, not on {host}",
            file=sys.stderr,
        )
        return 2
    uvicorn.run(create_app(settings), host=host, port=port)
    return 0


def _token() -> int:
    print(secrets.token_urlsafe(32))
    return 0


def _wait(raw_ids: list[str]) -> int:
    ids = card_ids(",".join(raw_ids))
    if not ids:
        print("no card ids given; pass one or more ids to `dequ wait`", file=sys.stderr)
        return 2
    token = os.environ.get("DEQU_TOKEN") or None
    base = os.environ.get("DEQU_URL") or "http://127.0.0.1:8790"
    try:
        return _wait_loop(ids, base.rstrip("/"), token)
    except KeyboardInterrupt:
        return 130


def _wait_loop(ids: list[str], base: str, token: str | None) -> int:
    url_prefix = f"{base}/api/results?{urllib.parse.urlencode({'ids': ','.join(ids)})}"
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    short_poll = False
    while True:
        if short_poll:
            url = f"{url_prefix}&{urllib.parse.urlencode({'wait': '0'})}"
        else:
            url = f"{url_prefix}&{urllib.parse.urlencode({'wait': '50', 'notify': 'firestore'})}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            # HTTPError is a subclass of URLError. Check it first, or a 401 is retried forever as a connection failure.
            if exc.code == 401:
                if token is None:
                    print("the server requires a token (401); set DEQU_TOKEN", file=sys.stderr)
                else:
                    print("the server rejected the token (401); check DEQU_TOKEN", file=sys.stderr)
                return 2
            print(f"the server returned {exc.code}", file=sys.stderr)
            return 1
        except (urllib.error.URLError, TimeoutError, OSError):
            print("cannot connect to the server", file=sys.stderr)
            time.sleep(_RETRY_SECONDS)
            continue
        except json.JSONDecodeError:
            print("cannot read the server response", file=sys.stderr)
            return 1
        finished = _finished(ids, payload)
        if finished is not None:
            return _report(finished)
        if not short_poll:
            bells = _pending_bells(ids, payload)
            if bells and _wait_for_bells(bells):
                short_poll = True
        if short_poll:
            time.sleep(_RETRY_SECONDS)


def _report(finished: tuple[str, dict[str, Any]]) -> int:
    card_id, item = finished
    status = item.get("status")
    body: dict[str, Any] = {"id": card_id, "status": status}
    if item.get("answer") is not None:
        body["answer"] = item["answer"]
    print(json.dumps(body, ensure_ascii=False))
    if status == "answered":
        return 0
    if status == "gone":
        return 3
    return 1


def _finished(ids: list[str], payload: Any) -> tuple[str, dict[str, Any]] | None:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, dict):
        return None
    for card_id in ids:
        item = results.get(card_id)
        if isinstance(item, dict) and item.get("status") not in (None, "pending"):
            return card_id, item
    return None


def _pending_bells(ids: list[str], payload: Any) -> list[FirestoreBell]:
    """The bells to watch when every pending card advertises one."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, dict):
        return []
    bells: list[FirestoreBell] = []
    seen = set()
    for card_id in ids:
        item = results.get(card_id)
        if not isinstance(item, dict) or item.get("status") != "pending":
            return []
        bell = _firestore_bell(item.get("notification"))
        if bell is None:
            return []
        key = (bell.project, bell.database, bell.bell)
        if key not in seen:
            seen.add(key)
            bells.append(bell)
    return bells


def _firestore_bell(value: Any) -> FirestoreBell | None:
    if not isinstance(value, dict):
        return None
    project = value.get("project")
    database = value.get("database")
    bell = value.get("bell")
    expires_at = value.get("expires_at")
    if not all(isinstance(part, str) and part for part in (project, database, bell, expires_at)):
        return None
    try:
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return FirestoreBell(project=project, database=database, bell=bell, expires_at=expires)


def _wait_for_bells(bells: list[FirestoreBell]) -> bool:
    """Block until one bell document changes, a bell expires, or the listen fails.

    Return True to switch to short HTTP checks when Firestore notifications are unavailable.
    """
    if _bell_wait_seconds(bells) <= 0:
        # The descriptor was already past on entry, so pause before retrying instead of spinning on clock skew.
        time.sleep(_RETRY_SECONDS)
        return False
    try:
        return asyncio.run(_listen_for_bells(bells))
    except ImportError:
        return True


async def _listen_for_bells(bells: list[FirestoreBell]) -> bool:
    """Run one Listen call per bell and cancel them together when one answers or fails."""
    # The imports are lazy so a self-hosted wait never loads the Firestore SDK.
    import grpc
    from google.api_core.exceptions import GoogleAPIError
    from google.auth.credentials import AnonymousCredentials
    from google.auth.exceptions import GoogleAuthError
    from google.cloud.firestore_v1.services.firestore.async_client import FirestoreAsyncClient
    from google.cloud.firestore_v1.services.firestore.transports.grpc_asyncio import (
        FirestoreGrpcAsyncIOTransport,
    )
    from google.cloud.firestore_v1.types import ListenRequest, Target, TargetChange

    clients: dict[tuple[str, str], Any] = {}
    streams: list[Any] = []
    tasks: list[asyncio.Task[bool]] = []
    emulator = os.environ.get("FIRESTORE_EMULATOR_HOST")

    def database_name(bell: FirestoreBell) -> str:
        return f"projects/{bell.project}/databases/{bell.database}"

    def client_for(bell: FirestoreBell) -> Any:
        key = (bell.project, bell.database)
        client = clients.get(key)
        if client is None:
            if emulator:
                channel = grpc.aio.insecure_channel(emulator)
                transport = FirestoreGrpcAsyncIOTransport(
                    host=emulator, channel=channel, credentials=AnonymousCredentials()
                )
                client = FirestoreAsyncClient(transport=transport)
            else:
                client = FirestoreAsyncClient(credentials=AnonymousCredentials())
            clients[key] = client
        return client

    async def request_for(database: str, document: str) -> Any:
        yield ListenRequest(
            database=database,
            add_target=Target(
                documents=Target.DocumentsTarget(documents=[document]),
                target_id=_FIRESTORE_TARGET_ID,
            ),
        )
        # Keep the write side open; closing it makes the server end the Listen stream.
        await asyncio.Event().wait()

    async def watch(bell: FirestoreBell) -> bool:
        """Return True when the listen failed and False when the bell document changed."""
        database = database_name(bell)
        document = f"{database}/documents/bells/{bell.bell}"
        try:
            # The generated client.listen appends an empty x-goog-request-params header, which a
            # named database rejects; the transport call sends only the resource prefix and no retry.
            stream = client_for(bell).transport.listen(
                request_for(database, document),
                metadata=[("google-cloud-resource-prefix", database)],
            )
            streams.append(stream)
            async for response in stream:
                kind = response._pb.WhichOneof("response_type")
                if kind == "target_change":
                    change = response.target_change
                    if change.target_ids and _FIRESTORE_TARGET_ID not in change.target_ids:
                        continue
                    if change.target_change_type in (
                        TargetChange.TargetChangeType.REMOVE,
                        TargetChange.TargetChangeType.RESET,
                    ):
                        return True
                elif kind == "document_change":
                    change = response.document_change
                    if _FIRESTORE_TARGET_ID in change.target_ids and change.document.name == document:
                        return False
            return True
        except (grpc.RpcError, GoogleAPIError, GoogleAuthError):
            return True

    try:
        tasks = [asyncio.create_task(watch(bell)) for bell in bells]
        done, _ = await asyncio.wait(
            tasks, timeout=_bell_wait_seconds(bells), return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            return False
        results = [task.result() for task in done]
        return any(results)
    finally:
        for stream in streams:
            stream.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for client in clients.values():
            await client.transport.close()


def _bell_wait_seconds(bells: list[FirestoreBell]) -> float:
    remaining = (min(bell.expires_at for bell in bells) - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, remaining)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dequ")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the server")
    serve.add_argument("--config", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8790)

    sub.add_parser("token", help="create a token")

    wait = sub.add_parser("wait", help="wait for the answer to a card")
    wait.add_argument("ids", nargs="+")

    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args.config, args.host, args.port)
    if args.command == "token":
        return _token()
    return _wait(args.ids)


if __name__ == "__main__":
    sys.exit(main())
