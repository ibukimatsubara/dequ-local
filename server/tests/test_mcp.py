"""Agents ask for decisions and receive answers over MCP. Starts a real server and connects with the official MCP client."""

import asyncio
import json
import threading
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from support import AUTH, CARD, TOKEN

def payload(result):
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    return json.loads(result.content[0].text)


def with_session(url, action, token=TOKEN):
    async def run():
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        async with create_mcp_http_client(headers=headers) as http:
            async with streamable_http_client(f"{url}/mcp", http_client=http) as streams:
                read_stream, write_stream, *_ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await action(session)

    return asyncio.run(run())


def test_lists_ask_wait_record_and_withdraw_tools(server):
    tools = with_session(server, lambda session: session.list_tools())
    names = {tool.name: tool for tool in tools.tools}
    assert {"ask", "wait", "record", "withdraw"} <= set(names)
    assert all(names[name].description for name in ("ask", "wait", "record", "withdraw"))


def test_ask_creates_card_and_same_key_returns_same_card(server):
    async def action(session):
        first = payload(await session.call_tool("ask", {"card": {**CARD, "key": "shop-42/app-name"}}))
        again = payload(await session.call_tool("ask", {"card": {**CARD, "key": "shop-42/app-name"}}))
        return first, again

    first, again = with_session(server, action)
    assert first["created"] is True and first["status"] == "pending"
    assert again["id"] == first["id"] and again["created"] is False
    cards = httpx.get(f"{server}/api/cards", headers=AUTH).json()["cards"]
    assert [card["id"] for card in cards] == [first["id"]]


def test_answer_on_screen_reaches_waiting_agent(server):
    async def action(session):
        asked = payload(await session.call_tool("ask", {"card": CARD}))
        still = payload(await session.call_tool("wait", {"ids": [asked["id"]], "max_wait_seconds": 1}))

        def answer_soon():
            time.sleep(0.5)
            httpx.post(f"{server}/api/cards/{asked['id']}/answer", json={"option": "company", "comment": "Company name"}, headers=AUTH)

        threading.Thread(target=answer_soon).start()
        done = payload(await session.call_tool("wait", {"ids": [asked["id"]], "max_wait_seconds": 20}))
        return asked, still, done

    asked, still, done = with_session(server, action)
    assert still["results"][asked["id"]]["status"] == "pending"
    assert done["results"][asked["id"]] == {"status": "answered", "answer": {"option": "company", "comment": "Company name"}}


def test_recorded_decision_appears_in_history(server):
    record = {
        "agent": {"kind": "codex", "name": "Codex", "where": "work PC"},
        "question": "Bundle small dependency updates?",
        "chose": "Bundle them",
        "why": "The tests pass.",
    }
    with_session(server, lambda session: session.call_tool("record", {"record": record}))
    entries = httpx.get(f"{server}/api/history", headers=AUTH).json()["entries"]
    assert entries[0]["by"] == "ai" and entries[0]["question"] == "Bundle small dependency updates?"


def test_waiting_on_withdrawn_card_reports_gone(server):
    async def action(session):
        asked = payload(await session.call_tool("ask", {"card": CARD}))
        await session.call_tool("withdraw", {"id": asked["id"]})
        return asked, payload(await session.call_tool("wait", {"ids": [asked["id"]], "max_wait_seconds": 1}))

    asked, result = with_session(server, action)
    assert result["results"][asked["id"]]["status"] == "gone"


def test_invalid_card_returns_error_agent_can_fix(server):
    async def action(session):
        return await session.call_tool("ask", {"card": {**CARD, "task": "a" * 81}})

    result = with_session(server, action)
    assert result.is_error if hasattr(result, "is_error") else result.isError
    assert "task" in json.dumps([block.model_dump() for block in result.content], ensure_ascii=False)


def test_mcp_requires_token(server):
    response = httpx.post(f"{server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                          headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401


def test_rejects_unallowed_host(server):
    response = httpx.post(f"{server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                          headers={**AUTH, "Accept": "application/json, text/event-stream", "Host": "evil.example"})
    assert response.status_code in (400, 403, 421)


def test_withdrawing_an_answered_card_reports_a_tool_error(server):
    card_id = httpx.post(f"{server}/api/cards", json=CARD, headers=AUTH).json()["id"]
    answer = {"option": "company", "comment": "Company name"}
    assert httpx.post(f"{server}/api/cards/{card_id}/answer", json=answer, headers=AUTH).status_code == 204

    async def withdraw(session):
        return await session.call_tool("withdraw", {"id": card_id})

    result = with_session(server, withdraw)
    assert result.is_error if hasattr(result, "is_error") else result.isError
    assert "already answered" in result.content[0].text
