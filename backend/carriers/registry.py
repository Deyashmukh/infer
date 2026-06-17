"""Carrier registry: maps carrier value strings to their carrier modules."""

from __future__ import annotations

from backend.browser import CarrierModule
from backend.carriers import geico, lm
from spike.config import Config

_MODULES: dict[str, CarrierModule] = {
    "liberty_mutual": lm,  # type: ignore[dict-item]
    "geico": geico,  # type: ignore[dict-item]
}


def carrier_module(carrier: str) -> CarrierModule:
    """Return the carrier module for *carrier*, or raise on unknown value."""
    try:
        return _MODULES[carrier]
    except KeyError:
        known = ", ".join(sorted(_MODULES))
        raise ValueError(f"unknown carrier {carrier!r} (known: {known})") from None


def login_url_for(cfg: Config, carrier: str) -> str:
    """Return the login URL for *carrier* from *cfg*, or raise if unset/unknown."""
    if carrier == "liberty_mutual":
        return cfg.lm_login_url
    if carrier == "geico":
        if cfg.geico_login_url is None:
            raise ValueError("GEICO_LOGIN_URL is not configured")
        return cfg.geico_login_url
    known = ", ".join(sorted(_MODULES))
    raise ValueError(f"unknown carrier {carrier!r} (known: {known})")
