from __future__ import annotations

from typing import Any

from spike.config import Config


def build_session_params(
    config: Config,
    context_id: str | None = None,
    advanced_stealth: bool = False,
) -> dict[str, Any]:
    """Build the Browserbase create-session payload.

    Residential proxy + US geolocation is the baseline (spec §3). advanced_stealth
    (Browserbase "Verified", Scale-gated) is an escalation lever, off by default
    per the start-cheap budget posture (spec §2).
    """
    browser_settings: dict[str, Any] = {
        **({"context": {"id": context_id, "persist": True}} if context_id is not None else {}),
        **({"advancedStealth": True} if advanced_stealth else {}),
    }
    return {
        "projectId": config.browserbase_project_id,
        "proxies": [{"type": "browserbase", "geolocation": {"country": "US"}}],
        "keepAlive": True,
        "browserSettings": browser_settings,
    }
