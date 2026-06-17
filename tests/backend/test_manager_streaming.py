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


async def test_serves_only_first_doc():
    # User requirement: one document per carrier. Extra docs are dropped — they add wall-clock
    # time and risk a flaky doc failing the session, without improving first-doc latency.
    driver = FakeDriver(docs=[("doc-0", "A"), ("doc-1", "B"), ("doc-2", "C")], fetch_delay=0.1)
    reg, mgr = make_manager(driver)
    s = mgr.start("liberty_mutual", "u", "p")
    await _wait_status(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait_status(reg, s.id, SessionStatus.READY)
    sess = reg.get(s.id)
    assert set(sess.documents) == {"doc-0"}
    assert [r.doc_id for r in sess.doc_refs] == ["doc-0"]
    # Wait for the background task to finish; it must NOT fetch doc-1/doc-2.
    if sess.task is not None:
        await sess.task
    assert set(sess.documents) == {"doc-0"} and driver.closed


async def test_zero_docs_fails():
    reg, mgr = make_manager(FakeDriver(docs=[]))
    s = mgr.start("liberty_mutual", "u", "p")
    await _wait_status(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait_status(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "DocFetchError"
