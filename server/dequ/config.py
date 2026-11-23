"""Server settings. A token is optional; when set it is read only from the environment."""

import tomllib
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Retention(BaseModel):
    """How long until cards are deleted, so card contents are not kept for long."""

    model_config = ConfigDict(extra="forbid")

    answered: timedelta = Field(default=timedelta(hours=1), ge=timedelta(0))
    """Time from answering a card until it is deleted."""
    pending: timedelta = Field(default=timedelta(days=3), ge=timedelta(0))
    """Time from creating an unanswered card until it is deleted."""


class Settings(BaseModel):
    """Settings for starting the server."""

    model_config = ConfigDict(extra="forbid")

    token: SecretStr | None = Field(default=None, min_length=16)
    """The shared token. When absent, the server is the same-computer deployment with no credential."""
    data_dir: Path
    web_dir: Path | None = None
    retention: Retention = Retention()
    allowed_hosts: list[str] = []
    """Host headers MCP accepts in addition to 127.0.0.1 and localhost."""


def load_settings(path: Path | None, env: Mapping[str, str]) -> Settings:
    """Build Settings from the config file and the environment. A token comes only from DEQU_TOKEN."""
    raw: dict[str, Any] = {}
    if path is not None:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"config file {path} must be a TOML table of settings")
        raw = dict(loaded)
    token = env.get("DEQU_TOKEN")
    # An explicitly empty token is a setup mistake, not a request for the credential-free deployment.
    if token is not None and not token.strip():
        raise ValueError("DEQU_TOKEN is set but empty; unset it for the same-computer deployment, or set a shared token")
    # Ignore a token in the file. The environment is the only source of the token.
    raw.pop("token", None)
    if token:
        raw["token"] = token
    data_dir = raw.get("data_dir", Path.home() / ".local" / "share" / "dequ")
    raw["data_dir"] = Path(data_dir).expanduser()
    if isinstance(raw.get("web_dir"), str):
        raw["web_dir"] = Path(raw["web_dir"]).expanduser()
    return Settings.model_validate(raw)
