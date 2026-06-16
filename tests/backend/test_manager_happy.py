import asyncio
import time

from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionManager, SessionRegistry


def make_manager(driver):
    reg = SessionRegistry()
    return reg, SessionManager(
        registry=reg,
        driver_factory=lambda: driver,
        login_url="https://lm/login",
        clock=time.monotonic,  # real clock; exact latency calc is covered by spike.timing tests
        mfa_deadline=5.0,
    )


async def _wait_status(reg, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"status never became {status}; is {reg.get(sid).status}")


async def test_reaches_awaiting_mfa_then_ready():
    driver = FakeDriver()
    reg, mgr = make_manager(driver)
    session = mgr.start("u", "p")
    await _wait_status(reg, session.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(session.id, "123456")
    await _wait_status(reg, session.id, SessionStatus.READY)
    s = reg.get(session.id)
    assert s.doc_refs and "doc-0" in s.documents
    assert s.latency_ms is not None and s.latency_ms >= 0.0  # MFA-submit -> first doc (ms)
    assert driver.closed is True  # cleanup ran on success
