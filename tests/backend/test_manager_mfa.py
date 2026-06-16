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
        login_url="x",
        clock=time.monotonic,
        mfa_deadline=5.0,
    )


async def _wait(reg, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}; is {reg.get(sid).status}")


async def test_mfa_retry_then_success_caps_attempts():
    driver = FakeDriver(mfa_fail_times=2)  # 2 rejects, 3rd accepted
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "bad1")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)  # back to awaiting after reject 1
    mgr.submit_mfa(s.id, "bad2")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)  # reject 2
    mgr.submit_mfa(s.id, "123456")
    await _wait(reg, s.id, SessionStatus.READY)
    assert reg.get(s.id).mfa_attempts == 3


async def test_mfa_exhausts_cap_then_fails():
    driver = FakeDriver(mfa_fail_times=99)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    for code in ("a", "b", "c"):
        mgr.submit_mfa(s.id, code)
        await asyncio.sleep(0.02)
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "MfaError"
    assert driver.closed is True
