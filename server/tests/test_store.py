"""Put, answer and delete cards. Cards survive a server restart and are deleted after the configured time."""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from dequ.config import Retention
from dequ.schema import Answer, CardRequest, DecisionRecord
from dequ.store import AlreadyAnswered, InvalidOption, NotFound, Store


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


AGENT = {"kind": "claude", "name": "Claude Code", "where": "laptop"}


def request(**changes):
    body = {
        "agent": AGENT,
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
    return CardRequest.model_validate(body)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def open_store(tmp_path, clock):
    """Open a store on the same saved data each time, the way a restarted server does."""
    path = tmp_path / "dequ.sqlite3"

    def open_(retention=None):
        return Store(path, retention or Retention(), clock)

    return open_


@pytest.fixture
def store(open_store):
    return open_store()


def test_put_card_is_pending(store):
    asked = store.ask(request())
    assert asked.created and asked.status == "pending"
    assert [card.id for card in store.pending()] == [asked.id]
    assert store.pending()[0].request.question == "Which app name on the consent screen?"


def test_pending_card_with_same_key_is_returned(store):
    first = store.ask(request(key="shop-42/app-name"))
    again = store.ask(request(key="shop-42/app-name"))
    assert again.id == first.id and not again.created
    assert len(store.pending()) == 1


def test_answered_card_leaves_pending_and_same_key_returns_answer(store):
    asked = store.ask(request(key="shop-42/app-name"))
    store.answer(asked.id, Answer(option="product"))
    assert store.pending() == []
    again = store.ask(request(key="shop-42/app-name"))
    assert again.id == asked.id and again.status == "answered"
    assert again.answer == Answer(option="product")


def test_results_tell_answered_pending_and_gone(store):
    answered = store.ask(request())
    waiting = store.ask(request())
    store.answer(answered.id, Answer(option="company", comment="Use the company name everywhere"))
    states = store.results([answered.id, waiting.id, "missing"])
    assert states[answered.id].status == "answered"
    assert states[answered.id].answer.comment == "Use the company name everywhere"
    assert states[waiting.id].status == "pending"
    assert states["missing"].status == "gone"


def test_card_cannot_be_answered_twice(store):
    asked = store.ask(request())
    store.answer(asked.id, Answer(option="product"))
    with pytest.raises(AlreadyAnswered):
        store.answer(asked.id, Answer(option="company"))


def test_missing_card_cannot_be_answered(store):
    with pytest.raises(NotFound):
        store.answer("missing", Answer(option="product"))


def test_unknown_option_cannot_be_chosen(store):
    asked = store.ask(request())
    with pytest.raises(InvalidOption):
        store.answer(asked.id, Answer(option="other"))


def test_answered_card_is_deleted_after_one_hour(store, clock):
    asked = store.ask(request())
    store.answer(asked.id, Answer(option="product"))
    clock.advance(minutes=59)
    assert store.results([asked.id])[asked.id].status == "answered"
    clock.advance(minutes=2)
    assert store.results([asked.id])[asked.id].status == "gone"


def test_unanswered_card_is_deleted_after_three_days(store, clock):
    asked = store.ask(request())
    clock.advance(days=3, minutes=-1)
    assert [card.id for card in store.pending()] == [asked.id]
    clock.advance(minutes=2)
    assert store.pending() == []
    assert store.results([asked.id])[asked.id].status == "gone"


def test_retention_is_configurable(open_store, clock):
    store = open_store(Retention(pending=timedelta(hours=2)))
    store.ask(request())
    clock.advance(hours=3)
    assert store.pending() == []


def test_key_of_deleted_card_can_be_reused(store, clock):
    first = store.ask(request(key="shop-42/app-name"))
    clock.advance(days=4)
    again = store.ask(request(key="shop-42/app-name"))
    assert again.created and again.id != first.id


def test_withdrawn_card_is_deleted(store):
    asked = store.ask(request(key="shop-42/app-name"))
    store.withdraw(asked.id)
    assert store.pending() == []
    assert store.results([asked.id])[asked.id].status == "gone"
    assert store.ask(request(key="shop-42/app-name")).created


def test_history_lists_human_answers_and_agent_decisions_newest_first(store, clock):
    asked = store.ask(request())
    clock.advance(minutes=1)
    store.answer(asked.id, Answer(option="product"))
    clock.advance(minutes=1)
    store.record(DecisionRecord(agent=AGENT, question="Write test names in English?", chose="English", why="Match the surrounding code."))
    history = store.history()
    assert [entry.by for entry in history] == ["ai", "human"]
    assert history[1].question == "Which app name on the consent screen?"
    assert history[1].chose == "Use the product name"


def test_cards_survive_reopening(open_store):
    asked = open_store().ask(request())
    assert [card.id for card in open_store().pending()] == [asked.id]


def test_concurrent_puts_with_same_key_make_one_card(open_store):
    open_store()
    ids = []

    def ask():
        ids.append(open_store().ask(request(key="shop-42/app-name")).id)

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(ids)) == 1


def test_card_ids_never_look_like_command_line_options(store):
    # Agents pass the id to `dequ wait <id>`; an id starting with "-" is parsed as an option.
    # With the old URL-safe ids about 1 in 64 started with "-", so 300 cards almost always hit one.
    ids = [store.ask(request()).id for _ in range(300)]
    assert [card_id for card_id in ids if card_id.startswith("-")] == []


def test_withdrawing_an_answered_card_keeps_answer_history_and_key(store):
    asked = store.ask(request(key="decision"))
    answer = Answer(option="product", comment="Keep the chosen name")
    store.answer(asked.id, answer)
    history = store.history()
    with pytest.raises(AlreadyAnswered):
        store.withdraw(asked.id)
    assert store.results([asked.id])[asked.id].answer == answer
    assert store.history() == history
    assert store.ask(request(key="decision")).id == asked.id
