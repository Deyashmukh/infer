import asyncio
import time

from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionManager, SessionRegistry


def make_manager(driver):
    reg = SessionRegistry()
    return reg, SessionManager(
        registry=reg,
        driver_factory=lambda carrier: driver,
        login_urls={"liberty_mutual": "https://lm/login"},
        clock=time.monotonic,
        mfa_deadline=5.0,
    )


async def _wait_status(reg, sid, status, timeout=3.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}; is {reg.get(sid).status}")


async def test_ready_after_first_doc_then_streams():
    driver = FakeDriver(docs=[("doc-0", "A"), ("doc-1", "B"), ("doc-2", "C")], fetch_delay=0.3)
    reg, mgr = make_manager(driver)
    s = mgr.start("liberty_mutual", "u", "p")
    await _wait_status(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait_status(reg, s.id, SessionStatus.READY)  # fires after doc-0, before the rest
    assert "doc-0" in reg.get(s.id).documents and len(reg.get(s.id).documents) < 3
    for _ in range(300):
        if len(reg.get(s.id).documents) == 3:
            break
        await asyncio.sleep(0.01)
    assert set(reg.get(s.id).documents) == {"doc-0", "doc-1", "doc-2"} and driver.closed


async def test_zero_docs_fails():
    reg, mgr = make_manager(FakeDriver(docs=[]))
    s = mgr.start("liberty_mutual", "u", "p")
    await _wait_status(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait_status(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "DocFetchError"
