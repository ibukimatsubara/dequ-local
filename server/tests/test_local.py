"""The same-computer deployment has no credential, and only this computer can use it."""

import httpx
import pytest

from dequ.app import create_app
from dequ.config import Settings
from support import CARD, serving
from test_mcp import with_session


@pytest.fixture
def url(tmp_path):
    with serving(create_app(Settings(data_dir=tmp_path / "data"))) as address:
        yield address


def test_health_names_local_mode_and_cards_need_no_token(url):
    assert httpx.get(f"{url}/api/health").json() == {"ok": True, "auth": "local"}
    assert httpx.get(f"{url}/api/cards").json() == {"cards": []}


def test_same_computer_can_ask_and_answer(url):
    created = httpx.post(f"{url}/api/cards", json=CARD).json()
    assert created["status"] == "pending"
    assert httpx.post(f"{url}/api/cards/{created['id']}/answer", json={"option": "product"}).status_code == 204
    result = httpx.get(f"{url}/api/results", params={"ids": created["id"]}).json()["results"][created["id"]]
    assert result["status"] == "answered"


def test_mcp_works_on_the_same_computer_without_a_token(url):
    tools = with_session(url, lambda session: session.list_tools(), token=None)
    assert {"ask", "wait", "record", "withdraw"} <= {tool.name for tool in tools.tools}


def test_a_non_loopback_host_is_rejected_even_for_health(url):
    assert httpx.get(f"{url}/api/cards", headers={"Host": "dequ.example"}).status_code == 403
    assert httpx.get(f"{url}/api/health", headers={"Host": "dequ.example"}).status_code == 403


def test_a_forwarded_remote_peer_is_rejected(url):
    assert httpx.get(f"{url}/api/cards", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 403


def test_browser_writes_must_match_the_origin_and_port(url):
    assert httpx.post(f"{url}/api/cards", json=CARD, headers={"Origin": url}).status_code == 201
    crossed_port = httpx.post(
        f"{url}/api/cards", json={**CARD, "key": "cross-port"}, headers={"Origin": "http://127.0.0.1:1"}
    )
    assert crossed_port.status_code == 403
    crossed_site = httpx.post(
        f"{url}/api/cards", json={**CARD, "key": "cross-site"}, headers={"Origin": "https://evil.example"}
    )
    assert crossed_site.status_code == 403
