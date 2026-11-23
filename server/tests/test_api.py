"""The HTTP entry point used by the screen and by agents using curl. Nothing is readable without a token, and answers reach agents right away."""

import threading
import time

import pytest
from starlette.testclient import TestClient

from dequ.app import create_app
from dequ.config import Settings

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SVG = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4="


def card(**changes):
    body = {
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
    body.update(changes)
    return body


@pytest.fixture
def client(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>DeQu</title>", encoding="utf-8")
    settings = Settings(token=TOKEN, data_dir=tmp_path / "data", web_dir=web)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def post_card(client, **changes):
    response = client.post("/api/cards", json=card(**changes), headers=AUTH)
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_api_requires_token(client):
    assert client.get("/api/cards").status_code == 401
    assert client.get("/api/cards", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/cards", headers=AUTH).status_code == 200


def test_health_check_needs_no_token(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_posted_card_appears_in_pending_list(client):
    created = post_card(client)
    assert created["created"] is True and created["status"] == "pending"
    cards = client.get("/api/cards", headers=AUTH).json()["cards"]
    assert [item["id"] for item in cards] == [created["id"]]
    assert cards[0]["question"] == "Which app name on the consent screen?"
    assert cards[0]["agent"]["name"] == "Claude Code"


def test_invalid_card_is_rejected_with_field_location(client):
    response = client.post("/api/cards", json=card(task="a" * 81), headers=AUTH)
    assert response.status_code == 422
    assert any("task" in error["loc"] for error in response.json()["errors"])


def test_same_key_does_not_create_second_card(client):
    first = post_card(client, key="shop-42/app-name")
    again = client.post("/api/cards", json=card(key="shop-42/app-name"), headers=AUTH)
    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["created"] is False


def test_canvas_for_screen_uses_from_to_and_only_supplied_icons(client):
    canvas = {
        "alt": "Flow from the user to sign-in",
        "panel": [320, 300],
        "nodes": [
            {"id": "user", "cx": 160, "top": 20, "name": "User", "icon": "lucide/user"},
            {"id": "tool", "cx": 160, "top": 170, "name": "In-house tool", "icon": "acme-tool"},
        ],
        "edges": [{"kind": "v", "from": "user", "to": "tool"}],
        "icon_data": {"acme-tool": SVG},
    }
    post_card(client, canvas=canvas)
    view = client.get("/api/cards", headers=AUTH).json()["cards"][0]["canvas"]
    assert view["edges"][0]["from"] == "user" and view["edges"][0]["to"] == "tool"
    assert view["icons"] == {"acme-tool": SVG}
    assert view["nodes"][0]["icon"] == "lucide/user"
    assert "icon_data" not in view


def test_answering_removes_card_and_returns_answer_to_agent(client):
    created = post_card(client)
    response = client.post(f"/api/cards/{created['id']}/answer", json={"option": "company", "comment": "Company name everywhere"}, headers=AUTH)
    assert response.status_code == 204
    assert client.get("/api/cards", headers=AUTH).json()["cards"] == []
    results = client.get("/api/results", params={"ids": created["id"]}, headers=AUTH).json()["results"]
    assert results[created["id"]] == {"status": "answered", "answer": {"option": "company", "comment": "Company name everywhere"}}


def test_answer_errors_return_matching_status(client):
    created = post_card(client)
    assert client.post("/api/cards/missing/answer", json={"option": "product"}, headers=AUTH).status_code == 404
    assert client.post(f"/api/cards/{created['id']}/answer", json={"option": "other"}, headers=AUTH).status_code == 422
    assert client.post(f"/api/cards/{created['id']}/answer", json={"option": "product"}, headers=AUTH).status_code == 204
    assert client.post(f"/api/cards/{created['id']}/answer", json={"option": "company"}, headers=AUTH).status_code == 409


def test_waiting_returns_as_soon_as_answered(client):
    created = post_card(client)

    def answer_soon():
        time.sleep(0.5)
        client.post(f"/api/cards/{created['id']}/answer", json={"option": "product"}, headers=AUTH)

    threading.Thread(target=answer_soon).start()
    started = time.monotonic()
    response = client.get("/api/results", params={"ids": created["id"], "wait": 20}, headers=AUTH)
    elapsed = time.monotonic() - started
    assert response.json()["results"][created["id"]]["status"] == "answered"
    assert elapsed < 5, f"took {elapsed:.1f} seconds after the answer"


def test_waiting_without_answer_returns_pending_at_limit(client):
    created = post_card(client)
    started = time.monotonic()
    response = client.get("/api/results", params={"ids": created["id"], "wait": 1}, headers=AUTH)
    assert response.json()["results"][created["id"]]["status"] == "pending"
    assert time.monotonic() - started >= 0.9


def test_withdrawn_card_is_reported_gone(client):
    created = post_card(client)
    assert client.delete(f"/api/cards/{created['id']}", headers=AUTH).status_code == 204
    results = client.get("/api/results", params={"ids": created["id"]}, headers=AUTH).json()["results"]
    assert results[created["id"]]["status"] == "gone"


def test_agent_decisions_appear_in_history(client):
    record = {
        "agent": {"kind": "codex", "name": "Codex", "where": "work PC"},
        "question": "Bundle small dependency updates?",
        "chose": "Bundle them",
        "why": "The tests pass.",
    }
    assert client.post("/api/records", json=record, headers=AUTH).status_code == 201
    entries = client.get("/api/history", headers=AUTH).json()["entries"]
    assert entries[0]["by"] == "ai" and entries[0]["chose"] == "Bundle them"


def test_all_responses_have_security_headers_and_no_cross_site_reads(client):
    for response in (client.get("/"), client.get("/api/cards", headers=AUTH), client.get("/api/health")):
        csp = response.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "img-src 'self' data:" in csp
        assert "frame-ancestors 'none'" in csp
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "access-control-allow-origin" not in response.headers


def test_built_screen_is_served_without_token(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "DeQu" in response.text


def test_oversized_request_is_rejected(client):
    response = client.post("/api/cards", content=b"x" * (3 * 1024 * 1024),
                           headers={**AUTH, "Content-Type": "application/json"})
    assert response.status_code == 413


def test_withdrawing_an_answered_card_returns_conflict(client):
    card_id = post_card(client)["id"]
    path = f"/api/cards/{card_id}"
    assert client.post(f"{path}/answer", json={"option": "product"}, headers=AUTH).status_code == 204
    assert client.delete(path, headers=AUTH).status_code == 409


def test_rejected_withdrawal_still_purges_expired_sqlite_answers(client, tmp_path):
    import sqlite3

    expired, current = (post_card(client)["id"] for _ in range(2))
    for card_id in (expired, current):
        assert client.post(f"/api/cards/{card_id}/answer", json={"option": "product"}, headers=AUTH).status_code == 204
    path = tmp_path / "data" / "dequ.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("UPDATE cards SET answered_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", expired))
    assert client.delete(f"/api/cards/{current}", headers=AUTH).status_code == 409
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id FROM cards WHERE id = ?", (expired,)).fetchone() is None
