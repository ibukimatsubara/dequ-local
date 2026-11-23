"""A deployment can give each token its own cards, the way a hosted service keeps its users apart.
Cards asked with one token are never visible to another token, over the API or over MCP."""

import threading
import time
from datetime import UTC, datetime

import httpx
import pytest

from dequ.app import build_app
from dequ.config import Retention
from dequ.store import Store

from support import CARD, serving
from test_mcp import payload, with_session

ALICE = "alice-token-0123456789abcdef"
BOB = "bob-token-0123456789abcdef00"
NOBODY = "nobody-token-0123456789abcd"
MCP_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
MCP_ACCEPT = {"Accept": "application/json, text/event-stream"}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class TwoUsers:
    def __init__(self, data_dir):
        now = lambda: datetime.now(UTC)  # noqa: E731
        self.stores = {
            ALICE: Store(data_dir / "alice.sqlite3", Retention(), now),
            BOB: Store(data_dir / "bob.sqlite3", Retention(), now),
        }

    def store_for(self, token):
        return self.stores.get(token)


@pytest.fixture
def url(tmp_path):
    with serving(build_app(TwoUsers(tmp_path))) as address:
        yield address


def cards(url, token):
    return [card["id"] for card in httpx.get(f"{url}/api/cards", headers=auth(token)).json()["cards"]]


def status(url, token, card_id):
    response = httpx.get(f"{url}/api/results", params={"ids": card_id}, headers=auth(token))
    return response.json()["results"][card_id]["status"]


def test_each_token_lists_only_its_own_cards(url):
    asked = httpx.post(f"{url}/api/cards", json=CARD, headers=auth(ALICE)).json()
    assert cards(url, ALICE) == [asked["id"]]
    assert cards(url, BOB) == []


def test_a_token_cannot_answer_withdraw_or_see_another_tokens_card(url):
    asked = httpx.post(f"{url}/api/cards", json=CARD, headers=auth(ALICE)).json()
    answer = httpx.post(f"{url}/api/cards/{asked['id']}/answer", json={"option": "product"}, headers=auth(BOB))
    assert answer.status_code == 404
    assert httpx.delete(f"{url}/api/cards/{asked['id']}", headers=auth(BOB)).status_code == 404
    assert status(url, BOB, asked["id"]) == "gone"
    assert status(url, ALICE, asked["id"]) == "pending"


def test_mcp_tools_use_the_cards_of_the_calling_token(url):
    async def ask(session):
        return payload(await session.call_tool("ask", {"card": CARD}))

    asked = with_session(url, ask, token=BOB)
    assert cards(url, BOB) == [asked["id"]]
    assert cards(url, ALICE) == []

    async def wait(session):
        return payload(await session.call_tool("wait", {"ids": [asked["id"]], "max_wait_seconds": 1}))

    assert with_session(url, wait, token=ALICE)["results"][asked["id"]]["status"] == "gone"


def test_history_is_kept_per_token(url):
    record = {
        "agent": {"kind": "codex", "name": "Codex", "where": "work PC"},
        "question": "Bundle the small dependency updates?",
        "chose": "Bundle them",
        "why": "The tests pass.",
    }
    assert httpx.post(f"{url}/api/records", json=record, headers=auth(ALICE)).status_code == 201
    assert len(httpx.get(f"{url}/api/history", headers=auth(ALICE)).json()["entries"]) == 1
    assert httpx.get(f"{url}/api/history", headers=auth(BOB)).json()["entries"] == []


def test_an_answer_wakes_the_agent_waiting_with_the_same_token(url):
    asked = httpx.post(f"{url}/api/cards", json=CARD, headers=auth(ALICE)).json()

    def answer_soon():
        time.sleep(0.5)
        httpx.post(f"{url}/api/cards/{asked['id']}/answer", json={"option": "company"}, headers=auth(ALICE))

    threading.Thread(target=answer_soon).start()
    started = time.monotonic()
    response = httpx.get(f"{url}/api/results", params={"ids": asked["id"], "wait": 20}, headers=auth(ALICE), timeout=30)
    assert response.json()["results"][asked["id"]]["status"] == "answered"
    assert time.monotonic() - started < 10


def test_an_unknown_token_is_rejected_on_the_api_and_mcp(url):
    assert httpx.get(f"{url}/api/cards", headers=auth(NOBODY)).status_code == 401
    assert httpx.post(f"{url}/mcp", json=MCP_LIST, headers={**auth(NOBODY), **MCP_ACCEPT}).status_code == 401
    assert httpx.get(f"{url}/api/cards").status_code == 401
    assert httpx.get(f"{url}/api/health").status_code == 200


def test_an_access_that_only_claims_to_be_local_still_needs_its_token(tmp_path):
    class ClaimsLocal(TwoUsers):
        local = True

    with serving(build_app(ClaimsLocal(tmp_path))) as address:
        assert httpx.get(f"{address}/api/cards").status_code == 401
        assert httpx.get(f"{address}/api/health").json() == {"ok": True}
        assert httpx.get(f"{address}/api/cards", headers=auth(ALICE)).status_code == 200


def test_app_mounted_under_a_subpath_still_requires_and_honors_the_token(tmp_path):
    from starlette.applications import Starlette
    from starlette.routing import Mount

    host = Starlette(routes=[Mount("/decisions", app=build_app(TwoUsers(tmp_path)))])
    with serving(host) as address:
        assert httpx.get(f"{address}/decisions/api/cards").status_code == 401
        assert httpx.get(f"{address}/decisions/api/cards", headers=auth(NOBODY)).status_code == 401
        response = httpx.get(f"{address}/decisions/api/cards", headers=auth(ALICE))
        assert response.status_code == 200 and response.json() == {"cards": []}


@pytest.fixture
def hosted_url(tmp_path):
    from dataclasses import replace
    from datetime import timedelta
    from dequ.store import FirestoreBell

    access = TwoUsers(tmp_path)
    store = access.store_for(ALICE)
    results = store.results
    hint = FirestoreBell("example-project", "named-db", "one-bell", datetime.now(UTC) + timedelta(days=1))

    def with_bell(ids):
        return {key: replace(item, notification=hint) if item.status == "pending" else item
                for key, item in results(ids).items()}

    store.results = with_bell
    with serving(build_app(access)) as address:
        with httpx.Client(base_url=address, headers=auth(ALICE), timeout=20) as client:
            card_id = client.post("/api/cards", json=CARD).json()["id"]
            yield address, client, card_id, hint


def test_hosted_rest_wait_only_returns_a_bell_when_requested(hosted_url):
    _, client, card_id, hint = hosted_url
    started = time.monotonic()
    offered = client.get("/api/results", params={"ids": card_id, "wait": 20, "notify": "firestore"})
    assert time.monotonic() - started < 10
    assert offered.json()["results"][card_id] == {
        "status": "pending",
        "notification": {"project": hint.project, "database": hint.database, "bell": hint.bell,
                         "expires_at": hint.expires_at.isoformat()},
    }
    started = time.monotonic()
    plain = client.get("/api/results", params={"ids": card_id, "wait": 1})
    assert time.monotonic() - started >= 0.9
    assert plain.json()["results"][card_id] == {"status": "pending"}


def test_hosted_mcp_wait_returns_pending_with_retry_guidance(hosted_url):
    address, _, card_id, _ = hosted_url

    async def wait(session):
        started = time.monotonic()
        result = await session.call_tool("wait", {"ids": [card_id], "max_wait_seconds": 20})
        assert time.monotonic() - started < 10
        return payload(result)

    reply = with_session(address, wait, token=ALICE)
    assert reply["results"][card_id]["status"] == "pending"
    assert reply["retry_after_seconds"] > 0
    assert "dequ wait" in reply["advice"]


@pytest.mark.parametrize("operation", ["answer", "withdraw"])
@pytest.mark.parametrize("owner", [ALICE, BOB], ids=["other-user", "same-user"])
def test_unrelated_card_changes_do_not_reread_the_waiters_store(tmp_path, operation, owner):
    from concurrent.futures import ThreadPoolExecutor
    from starlette.testclient import TestClient

    access = TwoUsers(tmp_path)
    bob_read = threading.Event()
    reads = []
    bob = access.store_for(BOB)
    results = bob.results

    def count_reads(ids):
        result = results(ids)
        reads.append(result)
        bob_read.set()
        return result

    bob.results = count_reads
    with TestClient(build_app(access)) as client, ThreadPoolExecutor() as pool:
        unrelated_id = client.post("/api/cards", json=CARD, headers=auth(owner)).json()["id"]
        bob_ids = [client.post("/api/cards", json=CARD, headers=auth(BOB)).json()["id"] for _ in range(2)]
        future = pool.submit(client.get, "/api/results", params={"ids": ",".join(bob_ids), "wait": 20}, headers=auth(BOB))
        assert bob_read.wait(3)
        path = f"/api/cards/{unrelated_id}"
        if operation == "answer":
            response = client.post(f"{path}/answer", headers=auth(owner), json={"option": "product"})
        else:
            response = client.delete(path, headers=auth(owner))
        assert response.status_code == 204
        assert client.post(f"/api/cards/{bob_ids[1]}/answer", headers=auth(BOB), json={"option": "company"}).status_code == 204
        assert future.result(timeout=5).json()["results"][bob_ids[1]]["status"] == "answered"
        assert len(reads) == 2
