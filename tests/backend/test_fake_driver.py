import pytest

from backend.browser import AuthStep, FakeDriver, FetchedDoc
from backend.models import BotChallengeError, CarrierAuthError, DocFetchError, MfaError


async def test_happy_path_flow():
    d = FakeDriver()
    await d.open_login("https://lm/login")
    assert await d.submit_credentials("u", "p") is AuthStep.NEEDS_MFA
    assert await d.submit_mfa("123456") is AuthStep.AUTHENTICATED
    docs = await d.list_documents()
    assert docs and docs[0].name
    blob = await d.fetch_document(docs[0])
    assert isinstance(blob, FetchedDoc) and blob.content.startswith(b"%PDF-")
    await d.close()
    assert d.closed is True


async def test_bot_block_on_open():
    d = FakeDriver(bot_block=True)
    with pytest.raises(BotChallengeError) as exc:
        await d.open_login("https://lm/login")
    assert exc.value.fields  # structured fields present


async def test_auth_failure():
    d = FakeDriver(auth_fail=True)
    await d.open_login("https://lm/login")
    with pytest.raises(CarrierAuthError):
        await d.submit_credentials("u", "p")


async def test_mfa_failure_then_success():
    d = FakeDriver(mfa_fail_times=1)
    await d.open_login("x")
    await d.submit_credentials("u", "p")
    with pytest.raises(MfaError):
        await d.submit_mfa("000000")
    assert await d.submit_mfa("123456") is AuthStep.AUTHENTICATED


async def test_doc_fetch_failure():
    d = FakeDriver(doc_fail=True)
    await d.open_login("x")
    await d.submit_credentials("u", "p")
    await d.submit_mfa("123456")
    with pytest.raises(DocFetchError):
        await d.list_documents()


async def test_hang_step_is_awaitable_for_timeout_tests():
    import asyncio

    d = FakeDriver(hang_on_mfa=True)
    await d.open_login("x")
    await d.submit_credentials("u", "p")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(d.submit_mfa("123456"), timeout=0.05)


async def test_close_is_idempotent():
    d = FakeDriver()
    await d.close()
    await d.close()
    assert d.closed is True
