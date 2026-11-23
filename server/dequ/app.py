"""The HTTP entry point used by the screen and by agents using curl."""

import asyncio
import hmac
import math
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .schema import Answer, CanvasSpec, CardRequest, DecisionRecord
from .store import (
    AlreadyAnswered,
    AskResult,
    Card,
    CardResult,
    CardStore,
    HistoryEntry,
    InvalidOption,
    NotFound,
    Store,
)

_MAX_BODY = 2 * 1024 * 1024
_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _Wake:
    """Wake only the results calls waiting on the card that changed, in the same process.

    Waiters are keyed by card id rather than by store, because a hosted deployment can build a new store wrapper for
    every request. The registry holds only cards someone is currently waiting on.
    """

    def __init__(self) -> None:
        self._waiters: dict[str, set[asyncio.Event]] = {}

    @contextmanager
    def waiting_on(self, ids: Sequence[str]) -> Iterator[asyncio.Event]:
        """Register before the store read, so a change after this point still sets the event."""
        event = asyncio.Event()
        wanted = set(ids)
        for card_id in wanted:
            self._waiters.setdefault(card_id, set()).add(event)
        try:
            yield event
        finally:
            for card_id in wanted:
                events = self._waiters.get(card_id)
                if events is None:
                    continue
                events.discard(event)
                if not events:
                    del self._waiters[card_id]

    def notify(self, card_id: str) -> None:
        events = self._waiters.pop(card_id, None)
        for event in events or ():
            event.set()

    async def wait(self, event: asyncio.Event, timeout: float) -> None:
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            return


async def wait_for_results(
    store: CardStore, wake: _Wake, ids: list[str], wait: float, notify: bool = False
) -> dict[str, CardResult]:
    """Wait until an answer or a withdrawal arrives. REST and MCP wait the same way.

    With notify, return as soon as every pending card advertises a notification. The caller can then wait on that
    notification instead of holding this request open.
    """
    if not ids or wait <= 0:
        return await run_in_threadpool(store.results, ids)
    deadline = time.monotonic() + wait
    while True:
        # Register before looking, so an answer or a withdrawal after this point sets the event.
        with wake.waiting_on(ids) as event:
            found = await run_in_threadpool(store.results, ids)
            if any(item.status != "pending" for item in found.values()):
                return found
            if notify and found and all(item.notification is not None for item in found.values()):
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return found
            await wake.wait(event, remaining)


class _Access(Protocol):
    def store_for(self, token: str) -> CardStore | None: ...


class TokenAccess:
    """The shared-token deployment: one store, accepted only for settings.token."""

    def __init__(self, token: str, store: CardStore) -> None:
        self._token = token.encode()
        self._store = store

    def store_for(self, token: str) -> CardStore | None:
        presented = token.encode()
        if hmac.compare_digest(presented, self._token):
            return self._store
        return None


class LocalAccess:
    """The same-computer deployment: one store, and no credential to present."""

    def __init__(self, store: CardStore) -> None:
        self._store = store

    def store(self) -> CardStore:
        return self._store


def is_loopback_host(host: str | None) -> bool:
    """True for a host name or address naming this computer, with any port."""
    if not host:
        return False
    try:
        # A CLI --host is a bare address, which urlsplit would not parse as a host name.
        return ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        name = urlsplit(f"//{host}").hostname
    except ValueError:
        return False
    if name is None:
        return False
    name = name.rstrip(".").lower()
    if name == "localhost":
        return True
    try:
        return ip_address(name).is_loopback
    except ValueError:
        return False


def _same_origin(origin: str, scheme: str, host: str) -> bool:
    """True when a browser Origin names the same scheme, host and port as its Host header."""
    try:
        parts = urlsplit(origin)
        here = urlsplit(f"//{host}")
        origin_port = parts.port or (443 if parts.scheme == "https" else 80)
        host_port = here.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or parts.scheme != scheme:
        return False
    origin_name = (parts.hostname or "").rstrip(".").lower()
    host_name = (here.hostname or "").rstrip(".").lower()
    return origin_name == host_name and origin_port == host_port


def _local_request_allowed(scope: Scope) -> bool:
    """Keep the credential-free deployment on this computer, and block cross-site browser writes."""
    headers = Headers(scope=scope)
    host = headers.get("host")
    if not is_loopback_host(host):
        return False
    # uvicorn trusts a forwarded address from a loopback proxy, so this is the direct or forwarded peer.
    client = scope.get("client")
    if not client or not is_loopback_host(client[0]):
        return False
    if scope.get("method", "GET").upper() in ("GET", "HEAD", "OPTIONS"):
        return True
    origin = headers.get("origin")
    # A browser sends Origin for cross-site writes, but not for same-origin ones or for non-browser clients.
    return origin is None or _same_origin(origin, scope.get("scheme", "http"), host or "")


class _Auth:
    def __init__(self, app: ASGIApp, access: _Access | LocalAccess) -> None:
        self.app = app
        self._access = access

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # The credential-free deployment is a distinct access type, not a flag a hosted access could fake.
        if isinstance(self._access, LocalAccess):
            if not _local_request_allowed(scope):
                await _error(403, "local DeQu accepts requests only from this computer")(scope, receive, send)
                return
            if _requires_token(_app_path(scope)):
                # MCP tools run later, on this same scope, so the resolved store has to ride the request.
                scope.setdefault("state", {})["store"] = self._access.store()
            await self.app(scope, receive, send)
            return
        if not _requires_token(_app_path(scope)):
            await self.app(scope, receive, send)
            return
        token = _bearer_token(scope)
        # A hosted store_for looks the token up over the network, so it must not run on the event loop.
        store = await run_in_threadpool(self._access.store_for, token) if token is not None else None
        if store is None:
            await _error(401, "authentication required: send Authorization: Bearer <DEQU_TOKEN>")(scope, receive, send)
            return
        # MCP tools run later, on this same scope, so the resolved store has to ride the request.
        scope.setdefault("state", {})["store"] = store
        await self.app(scope, receive, send)


class _App(Starlette):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        await super().__call__(scope, receive, send_with_headers)


def _app_path(scope: Scope) -> str:
    """The path inside this app. When a host mounts DeQu under a prefix, scope["path"] still includes the prefix."""
    path = scope.get("path", "")
    root = scope.get("root_path", "")
    return path[len(root):] if root and path.startswith(root) else path


def _requires_token(path: str) -> bool:
    if path == "/api/health":
        return False
    return path.startswith("/api/") or path == "/mcp" or path.startswith("/mcp/")


def _bearer_token(scope: Scope) -> str | None:
    authorization = Headers(scope=scope).get("authorization")
    if authorization is None or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ")


def _store(request: Request) -> CardStore:
    return request.state.store


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _validation_error(exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        {"errors": [{"loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()]},
        status_code=422,
    )


def _wait_seconds(raw: str | None) -> float | None:
    if raw is None or raw == "":
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        return None
    if math.isnan(value):
        return None
    return min(50.0, max(0.0, value))


def card_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _canvas_view(canvas: CanvasSpec) -> dict[str, Any]:
    payload = canvas.model_dump(mode="json", exclude={"icon_data"})
    icons: dict[str, str] = {
        part.icon: canvas.icon_data[part.icon]
        for part in (*canvas.nodes, *canvas.groups)
        if part.icon is not None and part.icon in canvas.icon_data
    }
    payload["icons"] = icons
    return payload


def _card_view(card: Card) -> dict[str, Any]:
    payload = card.request.model_dump(mode="json", exclude={"key"})
    if card.request.canvas is not None:
        payload["canvas"] = _canvas_view(card.request.canvas)
    payload["id"] = card.id
    payload["created_at"] = card.created_at.isoformat()
    return payload


def _ask_body(result: AskResult) -> dict[str, Any]:
    body: dict[str, Any] = {"id": result.id, "created": result.created, "status": result.status}
    if result.answer is not None:
        body["answer"] = result.answer.model_dump(mode="json")
    return body


def _result_view(result: CardResult, notify: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {"status": result.status}
    if result.answer is not None:
        body["answer"] = result.answer.model_dump(mode="json")
    if notify and result.status == "pending" and result.notification is not None:
        bell = result.notification
        body["notification"] = {
            "project": bell.project,
            "database": bell.database,
            "bell": bell.bell,
            "expires_at": bell.expires_at.isoformat(),
        }
    return body


def _history_view(entry: HistoryEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "by": entry.by,
        "agent": entry.agent.model_dump(mode="json"),
        "question": entry.question,
        "chose": entry.chose,
        "comment": entry.comment,
        "why": entry.why,
        "at": entry.at.isoformat(),
    }


class _Api:
    def __init__(self, wake: _Wake, *, local: bool = False) -> None:
        self._wake = wake
        self._local = local

    async def health(self, request: Request) -> Response:
        body: dict[str, Any] = {"ok": True}
        if self._local:
            body["auth"] = "local"
        return JSONResponse(body)

    async def create_card(self, request: Request) -> Response:
        try:
            card = CardRequest.model_validate_json(await request.body())
        except ValidationError as exc:
            return _validation_error(exc)
        result = await run_in_threadpool(_store(request).ask, card)
        return JSONResponse(_ask_body(result), status_code=201 if result.created else 200)

    async def list_cards(self, request: Request) -> Response:
        cards = await run_in_threadpool(_store(request).pending)
        return JSONResponse({"cards": [_card_view(card) for card in cards]})

    async def answer_card(self, request: Request) -> Response:
        try:
            answer = Answer.model_validate_json(await request.body())
        except ValidationError as exc:
            return _validation_error(exc)
        card_id = request.path_params["card_id"]
        try:
            await run_in_threadpool(_store(request).answer, card_id, answer)
        except NotFound:
            return _error(404, "card not found")
        except AlreadyAnswered:
            return _error(409, "card is already answered")
        except InvalidOption:
            return JSONResponse(
                {"errors": [{"loc": ["option"], "msg": "option is not one of the card's option ids"}]},
                status_code=422,
            )
        self._wake.notify(card_id)
        return Response(status_code=204)

    async def withdraw_card(self, request: Request) -> Response:
        card_id = request.path_params["card_id"]
        try:
            await run_in_threadpool(_store(request).withdraw, card_id)
        except NotFound:
            return _error(404, "card not found")
        except AlreadyAnswered:
            return _error(409, "card is already answered")
        self._wake.notify(card_id)
        return Response(status_code=204)

    async def results(self, request: Request) -> Response:
        wait = _wait_seconds(request.query_params.get("wait"))
        if wait is None:
            return JSONResponse({"errors": [{"loc": ["wait"], "msg": "wait must be a number of seconds"}]}, status_code=422)
        ids = card_ids(request.query_params.get("ids"))
        notify = request.query_params.get("notify") == "firestore"
        found = await wait_for_results(_store(request), self._wake, ids, wait, notify)
        return JSONResponse(
            {"results": {card_id: _result_view(item, notify=notify) for card_id, item in found.items()}}
        )

    async def create_record(self, request: Request) -> Response:
        try:
            record = DecisionRecord.model_validate_json(await request.body())
        except ValidationError as exc:
            return _validation_error(exc)
        record_id = await run_in_threadpool(_store(request).record, record)
        return JSONResponse({"id": record_id}, status_code=201)

    async def history(self, request: Request) -> Response:
        entries = await run_in_threadpool(_store(request).history)
        return JSONResponse({"entries": [_history_view(entry) for entry in entries]})


def build_app(
    access: _Access | LocalAccess,
    *,
    allowed_hosts: Sequence[str] = (),
    web_dir: Path | None = None,
) -> Starlette:
    # Importing at module top would make app and mcp_server import each other.
    from .mcp_server import create_mcp_app

    wake = _Wake()
    api = _Api(wake, local=isinstance(access, LocalAccess))
    mcp_app, session_manager = create_mcp_app(wake, allowed_hosts)
    routes: list[BaseRoute] = [
        Route("/api/health", api.health, methods=["GET"]),
        Route("/api/cards", api.list_cards, methods=["GET"]),
        Route("/api/cards", api.create_card, methods=["POST"]),
        Route("/api/cards/{card_id}/answer", api.answer_card, methods=["POST"]),
        Route("/api/cards/{card_id}", api.withdraw_card, methods=["DELETE"]),
        Route("/api/results", api.results, methods=["GET"]),
        Route("/api/records", api.create_record, methods=["POST"]),
        Route("/api/history", api.history, methods=["GET"]),
        # Mount only matches /mcp/. If /mcp fell through to a redirect, checks that do not follow redirects would never reach the host rejection.
        Route("/mcp", endpoint=mcp_app),
        Mount("/mcp", app=mcp_app),
    ]
    if web_dir is not None:
        routes.append(Mount("/", StaticFiles(directory=web_dir, html=True)))

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        # The parent does not run the lifespan of mounted child apps, so the MCP listener starts here.
        async with session_manager.run():
            yield

    return _App(
        routes=routes,
        middleware=[Middleware(_Auth, access=access)],
        max_body_size=_MAX_BODY,
        lifespan=lifespan,
    )


def create_app(settings: Settings, clock: Callable[[], datetime] | None = None) -> Starlette:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.data_dir / "dequ.sqlite3", settings.retention, clock or _utc_now)
    access = LocalAccess(store) if settings.token is None else TokenAccess(settings.token.get_secret_value(), store)
    return build_app(
        access,
        allowed_hosts=settings.allowed_hosts,
        web_dir=settings.web_dir,
    )
