from __future__ import annotations

from typing import Any

from spike.config import Config


def build_session_params(
    config: Config,
    context_id: str | None = None,
    advanced_stealth: bool = False,
    use_proxy: bool = True,
) -> dict[str, Any]:
    """Build kwargs for the Browserbase SDK ``sessions.create(**params)`` call.

    Residential proxy + US geolocation is the baseline (spec §3). ``advanced_stealth``
    (Browserbase "Verified"/Scale-gated) is an escalation lever, off by default per
    the start-cheap budget posture (spec §2). ``use_proxy`` can be turned off only for
    a free-plan diagnostic probe (proxies require a paid plan); the real gate needs it.
    Keys are the SDK's snake_case kwargs; ``browser_settings`` is omitted entirely
    unless a context or stealth is requested.
    """
    browser_settings: dict[str, Any] = {
        **({"context": {"id": context_id, "persist": True}} if context_id is not None else {}),
        **({"advanced_stealth": True} if advanced_stealth else {}),
    }
    params: dict[str, Any] = {
        "project_id": config.browserbase_project_id,
        "keep_alive": True,
    }
    if use_proxy:
        params["proxies"] = [{"type": "browserbase", "geolocation": {"country": "US"}}]
    if browser_settings:
        params["browser_settings"] = browser_settings
    return params


def create_session(config: Config, use_proxy: bool = True) -> tuple[str, str]:
    """Create a live Browserbase session; return ``(session_id, connect_url)``.

    ``connect_url`` is a live bearer credential — never log it raw (spec §8).
    """
    from browserbase import Browserbase

    bb = Browserbase(api_key=config.browserbase_api_key)
    params = build_session_params(config, config.browserbase_context_id, use_proxy=use_proxy)
    session = bb.sessions.create(**params)
    return session.id, session.connect_url


def release_session(config: Config, session_id: str) -> None:
    """Release a keep_alive session so it stops holding a concurrency slot.

    Disconnecting CDP does NOT end a keep_alive session — it stays RUNNING until
    released or idle-timeout. The live driver's close() must call this.
    """
    from browserbase import Browserbase

    bb = Browserbase(api_key=config.browserbase_api_key)
    bb.sessions.update(
        session_id, project_id=config.browserbase_project_id, status="REQUEST_RELEASE"
    )
