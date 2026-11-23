"""Rules for the card shape (schema). Matches the shape decided in the screen prototype (web/src/features/decide/sample.ts)."""

import pytest
from pydantic import ValidationError

from datetime import timedelta

from dequ.config import Retention
from dequ.schema import Answer, CardRequest, DecisionRecord


def card(**changes):
    base = {
        "agent": {"kind": "claude", "name": "Claude Code", "where": "laptop"},
        "task": "Add Google sign-in to the login screen.",
        "progress": "The button and the redirect handling are done.",
        "blocked": "The app name for the consent screen is not decided.",
        "question": "Which app name on the consent screen?",
        "options": [
            {"id": "product", "label": "Use the product name", "effect": "Clear to users at a glance."},
            {"id": "company", "label": "Use the company name", "effect": "Reusable across other products."},
        ],
        "recommended": "product",
        "reason": "Users see right away what they are granting access to.",
        "links": [{"kind": "issue", "label": "Issue #42", "url": "https://github.com/acme/shop/issues/42"}],
    }
    base.update(changes)
    return base


def canvas(**changes):
    base = {
        "alt": "Flow from the user to the login screen.",
        "panel": [320, 300],
        "nodes": [
            {"id": "user", "cx": 160, "top": 20, "name": "User", "icon": "lucide/user"},
            {"id": "login", "cx": 160, "top": 170, "name": "Login screen", "icon": "google"},
        ],
        "edges": [{"kind": "v", "from": "user", "to": "login", "color": "main", "label": "taps"}],
    }
    base.update(changes)
    return base


def test_accepts_card_shaped_like_screen_sample():
    CardRequest.model_validate(card(canvas=canvas(), details="## Background\n\nA long explanation."))


@pytest.mark.parametrize("field", ["task", "progress", "blocked"])
def test_context_fields_reject_more_than_80_characters(field):
    CardRequest.model_validate(card(**{field: "あ" * 80}))
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(**{field: "あ" * 81}))


@pytest.mark.parametrize("field", ["task", "progress", "blocked", "question"])
def test_context_fields_and_question_cannot_be_blank(field):
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(**{field: "  "}))


def test_rejects_single_option():
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(options=card()["options"][:1]))


def test_accepts_card_without_options_for_written_answer():
    CardRequest.model_validate(card(options=[], recommended=None, reason=None))


def test_rejects_five_or_more_options():
    options = [{"id": f"o{i}", "label": f"Plan {i}", "effect": "Result"} for i in range(5)]
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(options=options, recommended="o0"))


def test_recommended_must_be_an_option():
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(recommended="other"))


def test_recommended_requires_reason():
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(reason=None))


def test_option_ids_must_be_unique():
    options = [{"id": "a", "label": "Plan 1", "effect": "Result"}, {"id": "a", "label": "Plan 2", "effect": "Result"}]
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(options=options, recommended="a"))


def test_edges_must_connect_existing_nodes():
    bad = canvas(edges=[{"kind": "v", "from": "user", "to": "nowhere"}])
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(canvas=bad))


@pytest.mark.parametrize("icon", ["google", "aws/lambda", "gcp/cloud-run", "azure/app-service", "lucide/user"])
def test_icon_can_be_named(icon):
    nodes = [{"id": "a", "cx": 160, "top": 20, "name": "Node", "icon": icon}]
    CardRequest.model_validate(card(canvas=canvas(nodes=nodes, edges=[])))


def test_unnamed_icon_can_be_attached_as_image():
    nodes = [{"id": "a", "cx": 160, "top": 20, "name": "Node", "icon": "acme-tool"}]
    CardRequest.model_validate(card(canvas=canvas(
        nodes=nodes, edges=[], icon_data={"acme-tool": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4="})))


@pytest.mark.parametrize("value", [
    "https://acme.example/logo.svg",
    "data:text/html;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=",
    "data:image/svg+xml;base64,not base64!",
])
def test_attached_icon_must_be_image_data_url(value):
    nodes = [{"id": "a", "cx": 160, "top": 20, "name": "Node", "icon": "acme-tool"}]
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(canvas=canvas(nodes=nodes, edges=[], icon_data={"acme-tool": value})))


def test_attached_icon_is_limited_to_64kb():
    big = "A" * (64 * 1024 * 4 // 3 + 8)
    nodes = [{"id": "a", "cx": 160, "top": 20, "name": "Node", "icon": "acme-tool"}]
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(canvas=canvas(
            nodes=nodes, edges=[], icon_data={"acme-tool": "data:image/png;base64," + big})))


def test_rejects_invalid_icon_name():
    nodes = [{"id": "a", "cx": 160, "top": 20, "name": "Node", "icon": "../etc/passwd"}]
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(canvas=canvas(nodes=nodes, edges=[])))


def test_answer_needs_option_or_comment():
    Answer.model_validate({"option": "product", "comment": ""})
    Answer.model_validate({"option": None, "comment": "Neither; use the product's short name."})
    with pytest.raises(ValidationError):
        Answer.model_validate({"option": None, "comment": " "})


def test_card_with_options_requires_recommendation():
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(recommended=None, reason=None))


def test_card_accepts_key():
    CardRequest.model_validate(card(key="shop-42/consent-app-name"))
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(key="has a space"))


def test_card_accepts_the_recommended_repo_issue_topic_key():
    # The MCP instructions tell agents to use '<repo>#<issue>/<topic>'.
    CardRequest.model_validate(card(key="acme/shop#42/consent-app-name"))


def test_agent_decision_can_be_recorded():
    DecisionRecord.model_validate({
        "agent": {"kind": "codex", "name": "Codex", "where": "work PC"},
        "question": "Bundle dependency bumps in one PR?",
        "chose": "Bundle them",
        "why": "All are patch updates and the tests pass.",
    })
    with pytest.raises(ValidationError):
        DecisionRecord.model_validate({
            "agent": {"kind": "codex", "name": "Codex", "where": "work PC"},
            "question": "Bundle them?", "chose": "Bundle them",
        })


def test_default_retention_is_one_hour_answered_three_days_pending():
    retention = Retention()
    assert retention.answered == timedelta(hours=1)
    assert retention.pending == timedelta(days=3)
    assert Retention.model_validate({"pending": "P7D"}).pending == timedelta(days=7)


def test_node_outside_panel_is_rejected_with_its_id():
    nodes = [{"id": "far", "cx": 500, "top": 20, "name": "Node"}]
    with pytest.raises(ValidationError, match="far"):
        CardRequest.model_validate(card(canvas=canvas(nodes=nodes, edges=[])))
    nodes = [{"id": "low", "cx": 160, "top": 250, "name": "Node"}]
    with pytest.raises(ValidationError, match="low"):
        CardRequest.model_validate(card(canvas=canvas(nodes=nodes, edges=[])))


def test_group_outside_panel_is_rejected():
    groups = [{"x": 20, "y": 20, "w": 400, "h": 100, "label": "Frame"}]
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(canvas=canvas(groups=groups)))


def test_edge_to_same_node_is_rejected():
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(canvas=canvas(edges=[{"kind": "v", "from": "user", "to": "user"}])))


def test_edge_position_outside_panel_is_rejected():
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(canvas=canvas(edges=[{"kind": "v", "from": "user", "to": "login", "x": 999}])))


def test_canvas_json_uses_from_and_to():
    dumped = CardRequest.model_validate(card(canvas=canvas())).model_dump(mode="json")
    assert dumped["canvas"]["edges"][0]["from"] == "user"
    assert dumped["canvas"]["edges"][0]["to"] == "login"


def test_retention_cannot_be_negative():
    with pytest.raises(ValidationError):
        Retention.model_validate({"pending": "-P1D"})
    with pytest.raises(ValidationError):
        Retention.model_validate({"answered": "-PT1H"})


@pytest.mark.parametrize("blank", ["\u200b", " \u200b\u3000", "\ufeff"])
def test_question_with_only_invisible_characters_is_blank(blank):
    with pytest.raises(ValidationError):
        CardRequest.model_validate(card(question=blank))


def test_answer_with_only_invisible_characters_is_blank():
    with pytest.raises(ValidationError):
        Answer.model_validate({"option": None, "comment": "\u200b"})


def test_rejects_reason_without_recommendation():
    with pytest.raises(ValidationError, match="details"):
        CardRequest.model_validate(card(options=[], recommended=None, reason="It matters"))


def test_duplicate_option_id_error_includes_value():
    options = [{"id": "dup", "label": "Plan 1", "effect": "Result"}, {"id": "dup", "label": "Plan 2", "effect": "Result"}]
    with pytest.raises(ValidationError, match="dup"):
        CardRequest.model_validate(card(options=options, recommended="dup"))
