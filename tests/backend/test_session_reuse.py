"""Tests for session reuse via cached storage state.

Covers three scenarios:
1. Cached + resumable  -> skips AWAITING_MFA entirely, goes straight to READY.
2. Cached + expired    -> falls back to full login (reaches AWAITING_MFA).
3. Normal login        -> populates the cache after successful authentication.
"""

import asyncio
import time

from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionCache, SessionManager, SessionRegistry

_LM = "liberty_mutual"
_LOGIN_URLS = {_LM: "https://lm/login"}


def _make_manager(
    driver: FakeDriver,
    cache: SessionCache,
    mfa_deadline: float = 5.0,
) -> tuple[SessionRegistry, SessionManager]:
    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg,
        driver_factory=lambda carrier: driver,
        login_urls=_LOGIN_URLS,
        clock=time.monotonic,
        mfa_deadline=mfa_deadline,
        cache=cache,
    )
    return reg, mgr


async def _wait_status(
    reg: SessionRegistry,
    sid: str,
    status: SessionStatus,
    timeout: float = 1.0,
) -> None:
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"status never became {status}; is {reg.get(sid).status}")


async def test_cached_resumable_skips_mfa() -> None:
    """With a live cached session, the second run goes straight to READY without MFA."""
    driver = FakeDriver(resumable=True)

    cache = SessionCache(clock=time.monotonic)
    # Pre-seed the cache with a fake state for this account.
    cache.put(_LM, "user@example.com", {"cookies": [], "ts": 0})

    reg, mgr = _make_manager(driver, cache)
    session = mgr.start(_LM, "user@example.com", "secret")

    await _wait_status(reg, session.id, SessionStatus.READY)

    # Must never have entered AWAITING_MFA — that would mean MFA was needed.
    assert session.mfa_attempts == 0, "should have skipped MFA entirely"
    assert "doc-0" in reg.get(session.id).documents
    assert driver.closed is True


async def test_cached_expired_falls_back_to_full_login() -> None:
    """With an expired cached session (try_resume=False), the full login runs."""
    driver = FakeDriver(resumable=False)

    cache = SessionCache(clock=time.monotonic)
    cache.put(_LM, "user@example.com", {"cookies": [], "ts": 0})

    reg, mgr = _make_manager(driver, cache)
    session = mgr.start(_LM, "user@example.com", "secret")

    # Full login requires MFA.
    await _wait_status(reg, session.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(session.id, "123456")
    await _wait_status(reg, session.id, SessionStatus.READY)

    assert session.mfa_attempts == 1, "should have gone through MFA on the fallback path"
    assert "doc-0" in reg.get(session.id).documents
    assert driver.closed is True


async def test_successful_login_populates_cache() -> None:
    """After a normal login, the cache should contain the storage state."""
    driver = FakeDriver()

    cache = SessionCache(clock=time.monotonic)
    # No pre-seeded entry — fresh run.

    reg, mgr = _make_manager(driver, cache)
    session = mgr.start(_LM, "user@example.com", "secret")

    await _wait_status(reg, session.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(session.id, "123456")
    await _wait_status(reg, session.id, SessionStatus.READY)

    cached = cache.get(_LM, "user@example.com")
    assert cached is not None, "cache should be populated after a successful login"
    assert "cookies" in cached  # FakeDriver.storage_state() returns {"cookies": [], "ts": 0}
