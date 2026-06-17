import asyncio

from httpx import ASGITransport, AsyncClient

from backend.browser import FakeDriver
from backend.main import build_app
from backend.sessions import SessionManager, SessionRegistry


def client_for(driver):
    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg,
        driver_factory=lambda carrier: driver,
        login_urls={"liberty_mutual": "https://lm/login"},
        clock=lambda: 0.0,
        mfa_deadline=5.0,
    )
    app = build_app(manager=mgr, registry=reg)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), reg


async def _poll(c, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        r = await c.get(f"/sessions/{sid}")
        if r.json()["status"] == status:
            return r.json()
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}")


_NEW_SESSION = {"carrier": "liberty_mutual", "username": "u", "password": "p"}


async def test_full_flow_over_http():
    c, _ = client_for(FakeDriver())
    async with c:
        r = await c.post("/sessions", json=_NEW_SESSION)
        assert r.status_code == 201
        sid = r.json()["session_id"]
        body = await _poll(c, sid, "AWAITING_MFA")
        assert body["mfa_required"] is True
        r = await c.post(f"/sessions/{sid}/mfa", json={"code": "123456"})
        assert r.status_code == 200
        ready = await _poll(c, sid, "READY")
        assert ready["documents"][0]["doc_id"] == "doc-0"
        doc = await c.get(f"/sessions/{sid}/documents/doc-0")
        assert doc.status_code == 200
        assert doc.headers["content-type"] == "application/pdf"
        assert doc.content.startswith(b"%PDF-")


async def test_document_with_non_ascii_name_serves_ok():
    # Geico ID-card names contain an em dash; the Content-Disposition header must not crash on it.
    name = "Geico ID Card — 2009 LEXS RX 350 AWD"
    c, _ = client_for(FakeDriver(docs=[("doc-0", name)]))
    async with c:
        r = await c.post("/sessions", json=_NEW_SESSION)
        sid = r.json()["session_id"]
        await _poll(c, sid, "AWAITING_MFA")
        await c.post(f"/sessions/{sid}/mfa", json={"code": "123456"})
        await _poll(c, sid, "READY")
        doc = await c.get(f"/sessions/{sid}/documents/doc-0")
        assert doc.status_code == 200
        assert doc.content.startswith(b"%PDF-")
        cd = doc.headers["content-disposition"]
        # latin-1-safe fallback + RFC 5987 UTF-8 form carrying the percent-encoded em dash.
        assert cd.startswith("inline; filename=")
        assert "filename*=UTF-8''" in cd
        assert "%E2%80%94" in cd  # the em dash, percent-encoded
        cd.encode("latin-1")  # must be header-encodable (the original crash)


async def test_mfa_rejected_when_not_awaiting():
    c, _ = client_for(FakeDriver())
    async with c:
        r = await c.post("/sessions", json=_NEW_SESSION)
        sid = r.json()["session_id"]
        await _poll(c, sid, "AWAITING_MFA")
        await c.post(f"/sessions/{sid}/mfa", json={"code": "123456"})
        await _poll(c, sid, "READY")
        late = await c.post(f"/sessions/{sid}/mfa", json={"code": "999999"})
        assert late.status_code == 409


async def test_bot_block_surfaces_typed_error():
    c, _ = client_for(FakeDriver(bot_block=True))
    async with c:
        r = await c.post("/sessions", json=_NEW_SESSION)
        sid = r.json()["session_id"]
        body = await _poll(c, sid, "FAILED")
        assert body["error"]["type"] == "BotChallengeError"
        assert body["error"]["fields"]["kind"] == "AKAMAI_ACCESS_DENIED"


async def test_unknown_session_404():
    c, _ = client_for(FakeDriver())
    async with c:
        assert (await c.get("/sessions/nope")).status_code == 404


async def test_unknown_carrier_422():
    c, _ = client_for(FakeDriver())
    async with c:
        r = await c.post("/sessions", json={"carrier": "acme", "username": "u", "password": "p"})
        assert r.status_code == 422
