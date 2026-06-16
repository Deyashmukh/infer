import asyncio

from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionManager, SessionRegistry


def make_manager(driver, mfa_deadline=5.0):
    reg = SessionRegistry()
    return reg, SessionManager(
        registry=reg,
        driver_factory=lambda: driver,
        login_url="x",
        clock=lambda: 0.0,
        mfa_deadline=mfa_deadline,
    )


async def _wait(reg, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}; is {reg.get(sid).status}")


async def test_bot_block_fails_with_fields_and_closes():
    driver = FakeDriver(bot_block=True)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "BotChallengeError"
    assert reg.get(s.id).error.fields["kind"] == "AKAMAI_ACCESS_DENIED"
    assert driver.closed is True


async def test_auth_fail_closes_driver():
    driver = FakeDriver(auth_fail=True)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "CarrierAuthError"
    assert driver.closed is True


async def test_mfa_deadline_times_out_and_closes():
    driver = FakeDriver()
    reg, mgr = make_manager(driver, mfa_deadline=0.05)  # never submit a code
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.FAILED, timeout=2.0)
    assert reg.get(s.id).error.type == "SessionExpiredError"
    assert driver.closed is True


async def test_sweeper_cancels_and_closes():
    driver = FakeDriver()
    reg, mgr = make_manager(driver, mfa_deadline=999.0)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    await mgr.sweep(now=10_000.0, ttl=0.0)  # everything older than ttl=0 is swept
    await asyncio.sleep(0.02)
    assert driver.closed is True
    assert reg.get(s.id) is None


async def test_connection_lost_during_fetch_fails_and_closes():
    # fetch_document raises after a successful login+MFA -> DocFetchError, driver closed
    driver = FakeDriver(connection_lost_on_fetch=True)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "DocFetchError"
    assert driver.closed is True


async def test_driver_raised_cancellation_fails_and_closes():
    # driver raises CancelledError mid-flow -> _run records FAILED + re-raises; driver closed
    driver = FakeDriver(cancel_on_mfa=True)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "SessionExpiredError"
    assert driver.closed is True
