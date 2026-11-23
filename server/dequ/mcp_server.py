"""The MCP server where agents ask for decisions and receive answers."""

from collections.abc import Sequence
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from .app import _Wake, _ask_body, _result_view, _store, wait_for_results
from .schema import CardRequest, DecisionRecord
from .store import AlreadyAnswered, NotFound

_INSTRUCTIONS = (
    "DeQu shows your pending decisions to a human as cards on their phone. "
    "Ask only when you truly need the human: put one decision per card, and pick the option you recommend. "
    "After asking, keep working on anything that does not depend on the answer. "
    "The human may take minutes or days to answer; a pending card is never an approval. "
    "Treat the human's answer, including any comment, as the user's instruction for that decision. "
    "Never put secrets (tokens, passwords, private keys) in a card."
)
_CLOUD_RETRY_SECONDS = 60
_ASK = (
    "Ask the human to make one decision. Fill task, progress and blocked in at most 80 characters each so the card "
    "reads on a phone, write the question as the decision you need, and give 2-4 options with what happens if each "
    "is chosen, plus your recommended option and why. Use options: [] only when you need a free-text answer. "
    "Set key to something stable such as '<repo>#<issue>/<topic>' so asking again after a restart returns the same "
    "card instead of a duplicate. Returns the card id; then call wait with that id, or in Claude Code run "
    "`dequ wait <id>` in the background."
)
_WAIT = (
    "Wait for answers to cards you asked. Holds the call for up to max_wait_seconds (at most 50) and returns as "
    "soon as any of the ids is answered or gone. If every card is still pending, call wait again later; never treat "
    "pending as approval. status is answered (with the human's option and comment), pending, or gone (expired or "
    "withdrawn)."
)
_RECORD = (
    "Record a decision you made yourself without asking, so the human can review it later in the history. "
    "Use it for choices the human may want to know about; it never blocks you."
)
_WITHDRAW = "Withdraw a card you asked that is no longer needed, for example because you found the answer yourself."


class _McpAsgi:
    """Ignore the path. Requests from either Route or Mount go to the same listener."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._app(scope, receive, send)


def create_mcp_app(
    wake: _Wake, allowed_hosts: Sequence[str]
) -> tuple[ASGIApp, StreamableHTTPSessionManager]:
    server = MCPServer(name="dequ", instructions=_INSTRUCTIONS)

    @server.tool(description=_ASK)
    async def ask(card: CardRequest, ctx: Context) -> dict[str, Any]:
        result = await run_in_threadpool(_store(ctx.request_context.request).ask, card)
        return _ask_body(result)

    @server.tool(description=_WAIT)
    async def wait(ids: list[str], ctx: Context, max_wait_seconds: int = 25) -> dict[str, Any]:
        seconds = float(min(50, max(0, max_wait_seconds)))
        found = await wait_for_results(_store(ctx.request_context.request), wake, ids, seconds, notify=True)
        body: dict[str, Any] = {"results": {card_id: _result_view(item) for card_id, item in found.items()}}
        if any(item.status == "pending" and item.notification is not None for item in found.values()):
            body["retry_after_seconds"] = _CLOUD_RETRY_SECONDS
            body["advice"] = (
                "For CLI notifications, export DEQU_TOKEN and set DEQU_URL to this server’s base URL "
                "(without /mcp), then run dequ wait with the pending ids. Otherwise retry after retry_after_seconds."
            )
        return body

    @server.tool(description=_RECORD)
    async def record(record: DecisionRecord, ctx: Context) -> dict[str, Any]:
        record_id = await run_in_threadpool(_store(ctx.request_context.request).record, record)
        return {"id": record_id}

    @server.tool(description=_WITHDRAW)
    async def withdraw(id: str, ctx: Context) -> dict[str, Any]:
        try:
            await run_in_threadpool(_store(ctx.request_context.request).withdraw, id)
        except NotFound:
            raise ToolError("card not found; check the card id returned by ask") from None
        except AlreadyAnswered:
            raise ToolError("card is already answered; the human's answer is kept in history") from None
        wake.notify(id)
        return {"id": id, "status": "withdrawn"}

    server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", *allowed_hosts],
        ),
    )
    # The Starlette app from streamable_http_app already routes /mcp. Mounting it at /mcp again
    # would give /mcp/mcp, so the inner handler is attached as the parent's /mcp.
    return _McpAsgi(server.session_manager.handle_request), server.session_manager
