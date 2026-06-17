from httpx import ASGITransport, AsyncClient

from backend.browser import FakeDriver
from backend.main import build_app
from backend.sessions import SessionManager, SessionRegistry


async def test_health_returns_ok() -> None:
    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg,
        driver_factory=lambda carrier: FakeDriver(),
        login_urls={"liberty_mutual": "https://lm/login"},
        clock=lambda: 0.0,
        mfa_deadline=5.0,
    )
    app = build_app(manager=mgr, registry=reg)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
