from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_REQUIRED = (
    "BROWSERBASE_API_KEY",
    "BROWSERBASE_PROJECT_ID",
    "LM_USERNAME",
    "LM_PASSWORD",
    "LM_LOGIN_URL",
)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    browserbase_api_key: str
    browserbase_project_id: str
    lm_username: str
    lm_password: str
    lm_login_url: str
    browserbase_context_id: str | None


def load_config(env: Mapping[str, str]) -> Config:
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise ConfigError(f"Missing required config: {', '.join(missing)}")
    context_id = env.get("BROWSERBASE_CONTEXT_ID") or None
    return Config(
        browserbase_api_key=env["BROWSERBASE_API_KEY"],
        browserbase_project_id=env["BROWSERBASE_PROJECT_ID"],
        lm_username=env["LM_USERNAME"],
        lm_password=env["LM_PASSWORD"],
        lm_login_url=env["LM_LOGIN_URL"],
        browserbase_context_id=context_id,
    )
