from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_REQUIRED = ("LM_LOGIN_URL",)

class ConfigError(Exception): ...

@dataclass(frozen=True)
class Config:
    lm_login_url: str
    headless: bool
    chromium_args: list[str]
    proxy_server: str | None
    proxy_username: str | None
    proxy_password: str | None

def load_config(env: Mapping[str, str]) -> Config:
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise ConfigError(f"missing required env: {', '.join(missing)}")
    return Config(
        lm_login_url=env["LM_LOGIN_URL"],
        headless=env.get("HEADLESS", "true").lower() != "false",
        chromium_args=env.get("CHROMIUM_ARGS", "--disable-http2").split(),
        proxy_server=env.get("PROXY_SERVER") or None,
        proxy_username=env.get("PROXY_USERNAME") or None,
        proxy_password=env.get("PROXY_PASSWORD") or None,
    )
