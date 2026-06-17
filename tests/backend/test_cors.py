"""CORS allow-list: both Vite dev ports work by default; FRONTEND_ORIGIN overrides."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.browser import FakeDriver
from backend.main import _frontend_origins, build_app
from backend.sessions import SessionManager, SessionRegistry


def _app() -> object:
    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg,
        driver_factory=lambda carrier: FakeDriver(),
        login_urls={"liberty_mutual": "https://lm/login"},
        clock=lambda: 0.0,
        mfa_deadline=5.0,
    )
    return build_app(manager=mgr, registry=reg)


def test_default_origins_cover_both_vite_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    assert _frontend_origins() == ["http://localhost:5173", "http://localhost:5174"]


def test_frontend_origin_env_is_comma_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example.com, http://localhost:3000")
    assert _frontend_origins() == ["https://app.example.com", "http://localhost:3000"]


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://localhost:5174"])
async def test_preflight_allows_dev_ports(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.options(
            "/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
