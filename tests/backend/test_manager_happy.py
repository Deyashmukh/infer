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
    session = mgr.start("liberty_mutual", "u", "p")
    await _wait_status(reg, session.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(session.id, "123456")
    await _wait_status(reg, session.id, SessionStatus.READY)
    s = reg.get(session.id)
    assert s.doc_refs and "doc-0" in s.documents
    assert s.latency_ms is not None and s.latency_ms >= 0.0  # MFA-submit -> first doc (ms)
    assert driver.closed is True  # cleanup ran on success


async def test_carrier_flows_through_factory_and_session():
    """The carrier string passed to start() is recorded on the session and
    forwarded to the driver factory."""
    carriers_seen: list[str] = []

    def recording_factory(carrier: str) -> FakeDriver:
        carriers_seen.append(carrier)
        return FakeDriver()

    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg,
        driver_factory=recording_factory,
        login_urls={"liberty_mutual": "https://lm/login"},
        clock=time.monotonic,
        mfa_deadline=5.0,
    )
    session = mgr.start("liberty_mutual", "u", "p")
    await _wait_status(reg, session.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(session.id, "123456")
    await _wait_status(reg, session.id, SessionStatus.READY)
    assert session.carrier == "liberty_mutual"
    assert carriers_seen == ["liberty_mutual"]
    s = reg.get(session.id)
    assert s is not None and "doc-0" in s.documents
