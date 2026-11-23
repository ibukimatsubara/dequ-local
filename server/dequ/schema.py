"""The source of truth for the card shape (schema).

Defines `CardRequest`, which an agent sends to ask a person for a decision, `Answer`, which the person
sends back, and `DecisionRecord`, which keeps what an agent decided on its own.
DeQu only presents decisions clearly. Which ones to ask a person and which ones to decide alone is left
to the agent and the rules of the person using it.
One card carries exactly one decision. Three decisions make three cards.
Fields follow the same order as the screen (web/src/features/decide/). Length limits come from what can
be read in full at phone width (about 23 Japanese characters per line, so 3 lines are about 70; 80 leaves
some room).
"""

import base64
import binascii
import unicodedata
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, model_validator

# A node's footprint is wider than its tile and includes the name and role text (66 from the center on x, 110 high).
_NODE_HALF_WIDTH = 66
_NODE_HEIGHT = 110
_ICON_DATA_MAX_BYTES = 64 * 1024
_ICON_DATA_MIMES = frozenset({"image/svg+xml", "image/png", "image/webp"})


def _has_visible_text(value: str) -> bool:
    """Whether any character is left after removing whitespace and Unicode format characters (Cf). Only checks; never changes the string."""
    return any(not character.isspace() and unicodedata.category(character) != "Cf" for character in value)


def _not_blank(value: str) -> str:
    if not _has_visible_text(value):
        raise ValueError("must not be empty or contain only whitespace or invisible characters")
    return value


def _reject_duplicate_ids(where: str, ids: list[str]) -> None:
    seen: dict[str, int] = {}
    for index, item_id in enumerate(ids):
        if item_id in seen:
            raise ValueError(f"{where}[{index}].id {item_id!r} duplicates {where}[{seen[item_id]}].id; give each item a unique id")
        seen[item_id] = index


def _icon_data_url(value: str) -> str:
    header, separator, payload = value.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if separator != "," or not header.startswith("data:") or not header.endswith(";base64") or mime not in _ICON_DATA_MIMES:
        raise ValueError("icon_data values must be base64 data URLs of image/svg+xml, image/png or image/webp (data:<type>;base64,...)")
    # Reject base64 longer than 64KB without decoding it (65536 bytes encode to 87384 characters).
    if len(payload) > 4 * ((_ICON_DATA_MAX_BYTES + 2) // 3):
        raise ValueError("icon_data images must be 64KB or smaller")
    try:
        raw = base64.b64decode(payload, validate=True)
    except binascii.Error:
        raise ValueError("icon_data data URL is not valid base64") from None
    if len(raw) > _ICON_DATA_MAX_BYTES:
        raise ValueError("icon_data images must be 64KB or smaller")
    return value


def Text(max_length: int):
    """A string that is not only whitespace. The limit is what the screen can show in full."""
    return Annotated[str, Field(min_length=1, max_length=max_length), AfterValidator(_not_blank)]


Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")]

IconName = Annotated[str, Field(pattern=r"^(?:(?:aws|gcp|azure|lucide)/)?[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
IconData = Annotated[str, AfterValidator(_icon_data_url)]


class Model(BaseModel):
    # Unknown fields are not dropped silently; the sender gets an error.
    # Docstrings under fields go into the JSON Schema description, which agents see as the MCP tool description.
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)


class Agent(Model):
    """The agent asking for a decision and where it is running."""

    kind: Literal["claude", "codex", "grok", "muse", "pi", "dsh", "other"]
    name: Text(30)
    where: Text(30)


class Option(Model):
    id: Slug
    label: Text(24)
    """The option's name. Avoid jargon; the words alone should say what it does."""
    effect: Text(80)
    """What happens if this is chosen. Give both the upside and the downside."""


class Link(Model):
    kind: Literal["issue", "pr", "other"]
    label: Text(24)
    url: HttpUrl


class CanvasNode(Model):
    """A diagram node: a logo on a white tile with the name and role below. Coordinates are the tile's center x and top edge."""

    id: Slug
    cx: int = Field(ge=0)
    top: int = Field(ge=0)
    name: Text(14)
    role: Text(20) | None = None
    icon: IconName | None = None
    """Key of the image in icon_data. A key without a supplied image draws an initial."""


class CanvasGroup(Model):
    """A frame around things in the same runtime, vendor or repo. Use warm only to highlight a runtime."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    label: Text(24)
    tone: Literal["neutral", "warm"] = "neutral"
    icon: IconName | None = None
    """Key of the image in icon_data. A key without a supplied image draws an initial."""


class CanvasEdge(Model):
    """A vertical or horizontal line between nodes. main is the main flow, sub is everything else, fail is only for failures and rejections."""

    model_config = ConfigDict(
        extra="forbid",
        use_attribute_docstrings=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    kind: Literal["h", "v"]
    source: Slug = Field(alias="from")
    target: Slug = Field(alias="to")
    color: Literal["main", "sub", "fail"] = "sub"
    dashed: bool = False
    label: Text(12) | None = None
    x: int | None = None
    """Horizontal position of a v line. Defaults to the center of the source node. Shift it to place an outbound and a return line side by side."""
    y: int | None = None
    """Height of an h line. Defaults to the middle of the source node's tile."""


class CanvasSpec(Model):
    """A diagram. Uses the same dimensions as the excalidraw-desk diagram style; the screen draws it as SVG."""

    alt: Text(160)
    """The diagram described in words. Used by screen readers and when the diagram cannot be drawn."""
    panel: tuple[Annotated[int, Field(gt=0, le=1200)], Annotated[int, Field(gt=0, le=2400)]]
    """Width and height of the diagram. For phones, use a width around 320 and stack nodes vertically."""
    groups: list[CanvasGroup] = Field(default_factory=list, max_length=12)
    nodes: list[CanvasNode] = Field(default_factory=list, max_length=24)
    edges: list[CanvasEdge] = Field(default_factory=list, max_length=40)
    icon_data: dict[IconName, IconData] = Field(default_factory=dict, max_length=24)
    """Images keyed by the icon names used on nodes and groups (base64 data URLs of image/svg+xml, image/png or image/webp, 64KB or smaller)."""

    @model_validator(mode="after")
    def _fits_panel(self):
        width, height = self.panel
        _reject_duplicate_ids("nodes", [node.id for node in self.nodes])
        ids = {node.id for node in self.nodes}
        for node in self.nodes:
            if (
                node.cx - _NODE_HALF_WIDTH < 0
                or node.cx + _NODE_HALF_WIDTH > width
                or node.top + _NODE_HEIGHT > height
            ):
                raise ValueError(f"node {node.id!r} extends outside the panel; move it or enlarge panel")
        for group in self.groups:
            if group.x + group.w > width or group.y + group.h > height:
                raise ValueError(f"group {group.label!r} extends outside the panel; move it or enlarge panel")
        for index, edge in enumerate(self.edges):
            if edge.source == edge.target:
                raise ValueError(f"edges[{index}] connects a node to itself; from and to must differ")
            for end in (edge.source, edge.target):
                if end not in ids:
                    raise ValueError(f"edges[{index}] points to {end!r}, which is not in nodes")
            if edge.x is not None and not 0 <= edge.x <= width:
                raise ValueError(f"edges[{index}].x is outside the panel")
            if edge.y is not None and not 0 <= edge.y <= height:
                raise ValueError(f"edges[{index}].y is outside the panel")
        return self


class CardRequest(Model):
    """The card an agent sends to ask a person for a decision."""

    key: Annotated[str, Field(pattern=r"^[A-Za-z0-9._:/#-]{1,80}$")] | None = None
    """A mark for the same decision, so an agent that restarts and sends the same decision again does not create a second card.
    If a card with the same key is waiting for an answer, that card is returned instead of a new one. If it was answered, the answer is returned."""
    agent: Agent
    task: Text(80)
    """What the task is."""
    progress: Text(80)
    """What has been done so far."""
    blocked: Text(80)
    """What is in the way now (why the work is stopped)."""
    question: Text(40)
    """What needs to be decided. Becomes the card's heading."""
    options: list[Option] = Field(default_factory=list, max_length=4)
    """Options: none (to ask for a written answer) or 2 to 4."""
    recommended: Slug | None = None
    """The agent's own recommendation. Required (exactly one) when there are options."""
    reason: Text(80) | None = None
    """Why the recommendation is recommended."""
    links: list[Link] = Field(default_factory=list, max_length=4)
    canvas: CanvasSpec | None = None
    details: Text(20000) | None = None
    """Full explanation (Markdown): background, what was done, why the work is stopped, a comparison of options and any concerns, at length."""
    due: date | None = None

    @model_validator(mode="after")
    def _options_are_consistent(self):
        if len(self.options) == 1:
            raise ValueError("options must be empty or have 2 to 4 items (a single option is not a decision)")
        ids = [option.id for option in self.options]
        _reject_duplicate_ids("options", ids)
        if ids and self.recommended is None:
            raise ValueError("when there are options, set recommended to one option id")
        if self.recommended is not None:
            if self.recommended not in ids:
                raise ValueError("recommended must be one of the option ids")
            if self.reason is None:
                raise ValueError("when recommended is set, also write reason")
        if not ids and self.reason is not None:
            raise ValueError("reason is only for a recommendation; without options, put the background in details")
        return self


class Answer(Model):
    """A person's answer to a card: a chosen option, a written comment, or both."""

    option: Slug | None = None
    comment: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _has_content(self):
        if self.option is None and not _has_visible_text(self.comment):
            raise ValueError("an answer needs an option or a comment")
        return self


class DecisionRecord(Model):
    """A record of something an agent decided without asking. It appears in the history as decided by AI so a person can review it later."""

    agent: Agent
    question: Text(40)
    chose: Text(24)
    why: Text(80)
    links: list[Link] = Field(default_factory=list, max_length=4)
