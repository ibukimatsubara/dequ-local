"""The dequ command. It reads server settings and waits for answers while Claude Code runs it in the background."""

import io
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest

from dequ.config import load_settings

from support import AUTH, CARD, TOKEN


def run_dequ(*args, env=None, **kwargs):
    return subprocess.run([sys.executable, "-m", "dequ", *args], env={**os.environ, **(env or {})},
                          capture_output=True, text=True, **kwargs)


def test_settings_come_from_config_file_and_token_env(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        'data_dir = "/srv/dequ"\nallowed_hosts = ["box.tail1234.ts.net"]\n\n[retention]\npending = "PT2H"\n',
        encoding="utf-8",
    )
    settings = load_settings(config, {"DEQU_TOKEN": TOKEN})
    assert settings.token.get_secret_value() == TOKEN
    assert str(settings.data_dir) == "/srv/dequ"
    assert settings.retention.pending == timedelta(hours=2)
    assert settings.retention.answered == timedelta(hours=1)
    assert settings.allowed_hosts == ["box.tail1234.ts.net"]


def test_local_queue_opens_without_a_token(tmp_path):
    from dequ.app import create_app
    from support import serving

    config = tmp_path / "config.toml"
    config.write_text(f'data_dir = "{tmp_path}/data"')
    with serving(create_app(load_settings(config, {}))) as url:
        assert httpx.get(f"{url}/api/cards").json() == {"cards": []}


@pytest.mark.parametrize("token", ["", "   "])
def test_an_explicitly_empty_token_is_rejected(token):
    with pytest.raises(ValueError, match="DEQU_TOKEN is set but empty"):
        load_settings(None, {"DEQU_TOKEN": token})


def test_serve_refuses_a_non_loopback_bind_without_a_token(monkeypatch):
    from dequ import cli

    monkeypatch.delenv("DEQU_TOKEN", raising=False)
    started = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: started.append((args, kwargs)))
    assert cli._serve(None, "0.0.0.0", 8790) == 2
    assert started == []


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_serve_allows_a_loopback_bind_without_a_token(monkeypatch, host):
    from dequ import cli

    monkeypatch.delenv("DEQU_TOKEN", raising=False)
    monkeypatch.setattr(cli, "create_app", lambda settings: object())
    started = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: started.append((args, kwargs)))
    assert cli._serve(None, host, 8790) == 0
    assert len(started) == 1


def test_token_command_prints_hard_to_guess_string():
    first = run_dequ("token").stdout.strip()
    second = run_dequ("token").stdout.strip()
    assert len(first) >= 32 and first != second


def test_wait_prints_answer_and_exits(server):
    asked = httpx.post(f"{server}/api/cards", json=CARD, headers=AUTH).json()
    env = {"DEQU_URL": server, "DEQU_TOKEN": TOKEN}
    process = subprocess.Popen([sys.executable, "-m", "dequ", "wait", asked["id"]],
                               env={**os.environ, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def answer_soon():
        time.sleep(1)
        httpx.post(f"{server}/api/cards/{asked['id']}/answer", json={"option": "company", "comment": "Company name"}, headers=AUTH)

    threading.Thread(target=answer_soon).start()
    out, err = process.communicate(timeout=60)
    assert process.returncode == 0, err
    result = json.loads(out)
    assert result == {"id": asked["id"], "status": "answered", "answer": {"option": "company", "comment": "Company name"}}


def test_wait_reports_gone_card_and_exits_nonzero(server):
    asked = httpx.post(f"{server}/api/cards", json=CARD, headers=AUTH).json()
    httpx.delete(f"{server}/api/cards/{asked['id']}", headers=AUTH)
    finished = run_dequ("wait", asked["id"], env={"DEQU_URL": server, "DEQU_TOKEN": TOKEN}, timeout=60)
    assert finished.returncode != 0
    assert json.loads(finished.stdout)["status"] == "gone"


def test_wait_stops_with_reason_on_wrong_token(server):
    asked = httpx.post(f"{server}/api/cards", json=CARD, headers=AUTH).json()
    finished = run_dequ("wait", asked["id"], env={"DEQU_URL": server, "DEQU_TOKEN": "wrong-token-0123456789"}, timeout=60)
    assert finished.returncode != 0
    assert "401" in finished.stderr or "token" in finished.stderr

def test_wait_requests_firestore_notifications_from_the_results_api(monkeypatch, capsys):
    from urllib.parse import parse_qs, urlsplit

    from dequ import cli

    calls = []

    def results(request, **kwargs):
        calls.append((parse_qs(urlsplit(request.full_url).query), request.get_header("Authorization")))
        return io.BytesIO(b'{"results":{"c1":{"status":"answered","answer":{"comment":"done"}}}}')

    monkeypatch.setenv("DEQU_TOKEN", TOKEN)
    monkeypatch.setattr(cli.urllib.request, "urlopen", results)
    assert cli.main(["wait", "c1"]) == 0
    assert calls == [({"ids": ["c1"], "wait": ["50"], "notify": ["firestore"]}, f"Bearer {TOKEN}")]
    assert json.loads(capsys.readouterr().out)["answer"]["comment"] == "done"


def test_wait_backs_off_if_the_clients_clock_has_already_passed_a_pending_expiry(monkeypatch):
    from dequ import cli

    hint = {"project": "test", "database": "named-db", "bell": "b",
            "expires_at": (datetime.now(UTC) - timedelta(seconds=2)).isoformat()}
    pending = {"status": "pending", "notification": hint}
    rows = iter([pending, pending, {"status": "gone"}])
    pauses = []

    def results(request, **kwargs):
        return io.BytesIO(json.dumps({"results": {"c1": next(rows)}}).encode())

    monkeypatch.setenv("DEQU_TOKEN", TOKEN)
    monkeypatch.setattr(cli.urllib.request, "urlopen", results)
    monkeypatch.setattr(cli.time, "sleep", pauses.append)
    assert cli.main(["wait", "c1"]) == 3
    assert any(seconds > 0 for seconds in pauses)


@pytest.mark.parametrize("sdk_installed", [True, False])
def test_hosted_wait_uses_short_http_checks_when_firestore_is_unavailable(monkeypatch, capsys, sdk_installed):
    from urllib.parse import parse_qs, urlsplit

    from dequ import cli

    hint = {"project": "test", "database": "named-db", "bell": "b",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}
    rows = iter([
        {"status": "pending", "notification": hint},
        {"status": "pending"},
        {"status": "answered", "answer": {"comment": "received"}},
    ])
    queries = []
    sleeps = []

    def results(request, **kwargs):
        assert request.get_header("Authorization") == f"Bearer {TOKEN}"
        queries.append(parse_qs(urlsplit(request.full_url).query))
        return io.BytesIO(json.dumps({"results": {"c1": next(rows)}}).encode())

    if sdk_installed:
        listen = Mock(return_value=True)
        monkeypatch.setattr(cli, "_wait_for_bells", listen)
    else:
        monkeypatch.setitem(sys.modules, "grpc", None)
    monkeypatch.setenv("DEQU_TOKEN", TOKEN)
    monkeypatch.setattr(cli.urllib.request, "urlopen", results)
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)

    assert cli.main(["wait", "c1"]) == 0
    assert json.loads(capsys.readouterr().out)["answer"]["comment"] == "received"
    assert queries == [
        {"ids": ["c1"], "wait": ["50"], "notify": ["firestore"]},
        {"ids": ["c1"], "wait": ["0"]},
        {"ids": ["c1"], "wait": ["0"]},
    ]
    assert all(seconds > 0 for seconds in sleeps) and len(sleeps) == 2
    if sdk_installed:
        listen.assert_called_once()


def test_wait_matches_the_card_ids_parsed_by_the_results_api(monkeypatch, capsys):
    from dequ import cli

    response = {"results": {"first": {"status": "pending"}, "second": {"status": "answered", "answer": {"comment": "done"}}}}
    fetch = Mock(side_effect=[io.BytesIO(json.dumps(response).encode())])
    monkeypatch.setenv("DEQU_TOKEN", TOKEN)
    monkeypatch.setattr(cli.urllib.request, "urlopen", fetch)
    assert cli.main(["wait", " first,second "]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "second"
    fetch.assert_called_once()


def test_wait_rejects_an_empty_id_list_without_contacting_the_server(monkeypatch):
    from dequ import cli

    fetch = Mock(side_effect=AssertionError("empty ids must not reach the results API"))
    monkeypatch.setenv("DEQU_TOKEN", TOKEN)
    monkeypatch.setattr(cli.urllib.request, "urlopen", fetch)
    assert cli.main(["wait", ", "]) == 2
    fetch.assert_not_called()


@pytest.fixture
def listen_service(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager

    import grpc
    from google.cloud.firestore_v1.types import ListenRequest, ListenResponse

    @contextmanager
    def start(handler):
        with ThreadPoolExecutor() as workers:
            service = grpc.server(workers)
            rpc = grpc.stream_stream_rpc_method_handler(
                handler, request_deserializer=ListenRequest.deserialize, response_serializer=ListenResponse.serialize
            )
            service.add_generic_rpc_handlers((grpc.method_handlers_generic_handler("google.firestore.v1.Firestore", {"Listen": rpc}),))
            port = service.add_insecure_port("127.0.0.1:0")
            service.start()
            monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", f"127.0.0.1:{port}")
            try:
                yield
            finally:
                service.stop(0).wait()

    return start


@pytest.mark.parametrize("already_signalled", [False, True])
def test_wait_reads_a_named_bell_without_polling_healthy_listeners(monkeypatch, listen_service, already_signalled):
    from google.cloud.firestore_v1.types import ListenResponse
    from dequ import cli

    database = "projects/example-project/databases/named-db"
    names = []
    listening = threading.Event()
    signalled = threading.Event()
    expiry = (datetime.now(UTC) + timedelta(seconds=10)).isoformat()

    def listen(requests, context):
        req = next(requests)
        assert req.database == database
        headers = dict(context.invocation_metadata())
        assert "authorization" not in headers
        assert headers.get("google-cloud-resource-prefix") == database
        assert headers.get("x-goog-request-params") != "", "an empty database routing header breaks named Firestore databases"
        closed = threading.Event()
        context.add_callback(closed.set)
        target = req.add_target
        name, = target.documents.documents
        names.append(name)
        if len(names) == 2:
            listening.set()
        if not already_signalled:
            yield ListenResponse(target_change={"target_change_type": "CURRENT", "target_ids": [target.target_id]})
        if name.endswith("/bell-two"):
            if not already_signalled:
                assert listening.wait(5)
                time.sleep(0.15)
            signalled.set()
            yield ListenResponse(document_change={"document": {"name": name}, "target_ids": [target.target_id]})
        if already_signalled:
            yield ListenResponse(target_change={"target_change_type": "CURRENT", "target_ids": [target.target_id]})
        closed.wait(10)

    fetches = []
    def results(req, **kwargs):
        assert req.get_header("Authorization") == f"Bearer {TOKEN}"
        fetches.append(req.full_url)
        rows = {key: {"status": "pending", "notification": {
            "project": "example-project", "database": "named-db", "bell": f"bell-{key}", "expires_at": expiry,
        }} for key in ("one", "two")}
        if len(fetches) > 1:
            assert signalled.is_set(), "a healthy idle listen must not poll the results API"
            rows["two"] = {"status": "answered", "answer": {"comment": "done"}}
        return io.BytesIO(json.dumps({"results": rows}).encode())

    monkeypatch.setenv("DEQU_TOKEN", TOKEN)
    monkeypatch.setattr(cli.urllib.request, "urlopen", results)
    with listen_service(listen):
        assert cli.main(["wait", "one", "two"]) == 0
    assert len(fetches) == 2
    assert f"{database}/documents/bells/bell-two" in names
    assert len(names) == len(set(names))
    if not already_signalled:
        assert set(names) == {f"{database}/documents/bells/bell-{key}" for key in ("one", "two")}


@pytest.mark.parametrize("failure", ["UNAVAILABLE", "PERMISSION_DENIED", "CANCELLED", "REMOVE", "REMOVE_ALL", "EOF"])
def test_listen_failure_does_not_hide_an_answer_until_expiry(monkeypatch, capsys, listen_service, failure):
    import grpc
    from google.cloud.firestore_v1.types import ListenResponse
    from dequ import cli

    attempts = []
    started = threading.Event()
    expiry = datetime.now(UTC) + timedelta(seconds=3)
    hint = {"project": "test", "database": "named-db", "bell": "b", "expires_at": expiry.isoformat()}

    def listen(requests, context):
        req = next(requests)
        attempts.append(time.monotonic())
        started.set()
        if failure in ("REMOVE", "REMOVE_ALL"):
            targets = [] if failure == "REMOVE_ALL" else [req.add_target.target_id]
            closed = threading.Event()
            context.add_callback(closed.set)
            yield ListenResponse(target_change={"target_change_type": "REMOVE", "target_ids": targets,
                                                "cause": {"code": 7, "message": "permission denied"}})
            closed.wait(10)
        elif failure != "EOF":
            context.abort(grpc.StatusCode[failure], "listen failed")

    def results(request, **kwargs):
        if datetime.now(UTC) >= expiry:
            row = {"status": "gone"}
        elif started.is_set():
            row = {"status": "answered", "answer": {"comment": "received"}}
        else:
            row = {"status": "pending", "notification": hint}
        return io.BytesIO(json.dumps({"results": {"card": row}}).encode())

    monkeypatch.setenv("DEQU_TOKEN", TOKEN)
    monkeypatch.setattr(cli, "_RETRY_SECONDS", 0.05)
    monkeypatch.setattr(cli.urllib.request, "urlopen", results)
    with listen_service(listen):
        assert cli.main(["wait", "card"]) == 0
        assert json.loads(capsys.readouterr().out)["answer"]["comment"] == "received"
        assert attempts and time.monotonic() - attempts[0] >= 0.04
        assert len(attempts) == 1, "one failed listen must return to DeQu before reconnecting"
